"""Explicit first-page, bounded-header extraction; never a full-document OCR fallback.

The recognizer, tensor preprocessing and detector parameters remain the full
pipeline's frozen ones. Embedded text must contain a genuine administrative
header before it can avoid OCR; an electronic signature alone is insufficient.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import time
import unicodedata
from pathlib import Path

from .contract import (MAX_IMAGE_PIXELS, MAX_PDF_PAGES, DemoConfigurationError,
                       sha256_file, validate_upload, verify_frozen_onnx)
from .engine import iter_images

ROI_FRACTIONS = (.45, .65, .80)
MAX_HEADER_LINES = 64
TITLE = re.compile(r"^(?:nghị định|nghị quyết|quyết định|công văn|thông tư|thông báo|báo cáo|kế hoạch|tờ trình|luật|bộ luật|pháp lệnh)$")
BODY = re.compile(r"^(?:căn cứ(?:\s|$|[:,])|kính gửi(?:\s|$|[:,])|điều\s+\d|quyết định\s*:|quyết nghị\s*:|nơi nhận\s*:)")
ISSUER = re.compile(r"^(?:chính phủ$|quốc hội$|thủ tướng chính phủ$|văn phòng|ủy ban|hội đồng|bộ\s|sở\s|cục\s|tổng cục|tòa án|viện kiểm sát)")
SIGNATURE = re.compile(r"^(?:(?:ký bởi|người ký|ngày ký|ký ngày|thời gian ký|cơ quan ký)\s*[:：]|digitally signed(?:\s|$)|signed by(?:\s|$)|signing time\s*[:：])")
NUMBER = re.compile(r"^số\s*[:：﹕]?\s*\S+\s*/\s*\S+")
DATE = re.compile(r"ngày\s+\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+\d{4}")
DETECTOR_FILES = {
    "inference.json": "0f1a7ec35da36173529c7a60238b7f7919e3831929c3f700ad90ad4896adecd5",
    "inference.pdiparams": "85218d2e3d98f5a21c58b4220627be923a97aee5db3cc71f39536ab31ac53960",
    "inference.yml": "7298d5ead546584af2504d03355f881ac7a7bc0eb1e282d3e159277c1d0af871",
}


def _disable_downloads():
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    from paddlex.inference.utils import official_models
    official_models._ModelManager._build_hosters = lambda self: []
    official_models.official_models._hosters = []


def offline_engine(provider):
    # Check before importing PaddleX, including when this endpoint is used without Electron.
    verify_frozen_onnx(require_weights=True)
    home = Path(os.environ.get("PADDLE_PDX_CACHE_HOME") or Path.home() / ".paddlex")
    folder = home / "official_models" / "PP-OCRv6_medium_det"
    for name, digest in DETECTOR_FILES.items():
        try:
            correct = sha256_file(folder / name) == digest
        except OSError:
            correct = False
        if not correct:
            raise DemoConfigurationError("Bóc tách nhanh cần detector local đúng SHA; không tải model: " + name)
    _disable_downloads()
    return provider()


def match_text(text):
    # Comparison only. Returned OCR/PDF strings are never normalized or repaired.
    return " ".join(unicodedata.normalize("NFC", str(text)).casefold().split())


def box_of(line):
    if "bbox" in line:
        return line["bbox"]
    points = line["polygon"]
    return [min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points)]


def overlap(a, b):
    area = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - area
    return area / union if union > 0 else 0


def covered_by(a, b):
    area = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    own = (a[2]-a[0])*(a[3]-a[1])
    return area / own if own > 0 else 0


def native_lines(page):
    import pymupdf as fitz

    lines, signatures = [], []
    data = page.get_text("dict", flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES)
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        block_text = "\n".join("".join(s.get("text", "") for s in line.get("spans", [])) for line in block.get("lines", []))
        signed = any(SIGNATURE.match(match_text(line)) for line in block_text.splitlines())
        if signed:
            signatures.append(list(block["bbox"]))
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", []))
            if not text.strip():
                continue
            item = {"text": text, "bbox": list(line["bbox"]), "geometry_source": "native_text"}
            if signed:
                item["metadata_excluded_reason"] = "electronic_signature"
            lines.append(item)
    return sorted(lines, key=lambda line: (box_of(line)[1], box_of(line)[0])), signatures


def assess_header(lines, roi_bottom, height):
    usable = [line for line in lines if not line.get("metadata_excluded_reason")]
    texts = [match_text(line["text"]) for line in usable]
    body_index = next((i for i, text in enumerate(texts) if BODY.match(text)), None)
    header = texts[:body_index] if body_index is not None else texts
    title_index = next((i for i, text in enumerate(header) if TITLE.fullmatch(text)), None)
    subject_index = next((i for i, text in enumerate(header) if re.match(r"^(?:v/v|về việc)(?:\s|:)", text)), None)
    anchor = subject_index if subject_index is not None else title_index
    subject = anchor is not None and (len(header) > anchor + 1 or subject_index is not None and len(header[subject_index]) > 5)
    evidence = {"document_number": any(NUMBER.match(t) for t in header),
                "issued_date": bool(DATE.search(" ".join(header))),
                "issuing_agency": any(ISSUER.match(t) for t in header),
                "document_heading": title_index is not None or subject_index is not None,
                "subject": bool(subject)}
    close_to_edge = body_index is None and bool(usable) and max(box_of(line)[3] for line in usable) >= roi_bottom - max(4, .012 * height)
    complete = all(evidence.values()) and body_index is not None and not close_to_edge
    return {"evidence": evidence, "header_complete": complete, "body_boundary_seen": body_index is not None,
            "bottom_line_clipped_or_close": close_to_edge,
            "missing": [key for key, exists in evidence.items() if not exists]}


def select_native_header(all_lines, width, height):
    attempts = []
    for fraction in ROI_FRACTIONS:
        bottom = height * fraction
        lines = []
        for line in all_lines:
            if box_of(line)[3] > bottom:
                continue
            lines.append(line)
            if not line.get("metadata_excluded_reason") and BODY.match(match_text(line["text"])):
                break
        status = assess_header(lines, bottom, height)
        attempts.append({"source": "native_text", "roi": [0, 0, width, bottom], "lines": len(lines), **status})
        if status["header_complete"]:
            return lines, attempts, status
    return [], attempts, status


def extract_metadata_fast(raw: bytes, filename: str, engine_provider) -> dict:
    """Called inside the app's existing sequential OCR lock, with its guarded cached engine provider."""
    from PIL import Image

    started = time.perf_counter()
    timings = dict.fromkeys(("inspection", "model_acquire", "model_init", "render", "detection", "crop", "recognition", "selection"), 0.0)
    extension = validate_upload(filename, raw)
    inspect_start = time.perf_counter()
    document = None
    signatures = []
    native_attempts = []
    try:
        if extension == ".pdf":
            import pymupdf as fitz
            try:
                document = fitz.open(stream=raw, filetype="pdf")
            except Exception as error:
                raise ValueError("PDF không thể đọc được hoặc đã hỏng.") from error
            if document.needs_pass:
                raise ValueError("PDF được bảo vệ bằng mật khẩu; hãy cung cấp bản không khóa.")
            if not 1 <= len(document) <= MAX_PDF_PAGES:
                raise ValueError(f"Demo hỗ trợ tối đa {MAX_PDF_PAGES} trang PDF mỗi lần.")
            source_count = len(document)
            page = document[0]  # No other page is opened/rendered/OCRed in this strategy.
            width, height = float(page.rect.width), float(page.rect.height)
            if width <= 0 or height <= 0:
                raise ValueError("Trang PDF có kích thước không hợp lệ.")
            all_native, signatures = native_lines(page)
            select_start = time.perf_counter()
            chosen, native_attempts, native_status = select_native_header(all_native, width, height)
            timings["selection"] = (time.perf_counter() - select_start) * 1000
            timings["inspection"] = (time.perf_counter() - inspect_start) * 1000 - timings["selection"]
            if chosen:
                roi = native_attempts[-1]["roi"]
                return result_record(filename, source_count, chosen, width, height, roi, "pdf_points", False,
                                     native_status, native_attempts, native_attempts, timings, started)
            zoom = min(2.0, math.sqrt(MAX_IMAGE_PIXELS / (width * height)))
            full_width, full_height = math.ceil(width * zoom), math.ceil(height * zoom)
            def render(fraction):
                clip = fitz.Rect(0, 0, width, height * fraction)
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, colorspace=fitz.csRGB, alpha=False)
                if pix.width * pix.height > MAX_IMAGE_PIXELS + 5000:
                    raise ValueError("Vùng PDF vượt giới hạn pixel.")
                return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            signature_boxes = [[v * zoom for v in box] for box in signatures]
        else:
            _, original = next(iter_images(raw, extension))
            source_count = 1
            full_width, full_height = original.size
            def render(fraction):
                return original.crop((0, 0, full_width, min(full_height, math.ceil(full_height * fraction))))
            signature_boxes = []
            timings["inspection"] = (time.perf_counter() - inspect_start) * 1000
        acquire_start = time.perf_counter()
        engine = offline_engine(engine_provider)  # Existing guarded lifetime cache is not bypassed.
        timings["model_acquire"] = (time.perf_counter() - acquire_start) * 1000
        fresh = getattr(engine, "initialization_started_at", -1) >= acquire_start
        timings["model_init"] = getattr(engine, "initialization_ms", 0.0) if fresh else 0.0
        cache = []
        attempts = []
        final_lines = []
        for fraction in ROI_FRACTIONS:
            t = time.perf_counter(); image = render(fraction); timings["render"] += (time.perf_counter()-t)*1000
            roi = [0, 0, image.width, image.height]
            t = time.perf_counter(); bgr, polygons = engine.detector.detect_regions(image); timings["detection"] += (time.perf_counter()-t)*1000
            lines = []
            reused = 0
            capped = False
            for polygon in polygons:
                if len(lines) >= MAX_HEADER_LINES:
                    capped = True
                    break
                t = time.perf_counter(); crop = engine.detector.crop_region(bgr, polygon); timings["crop"] += (time.perf_counter()-t)*1000
                digest = hashlib.sha256(crop.tobytes()).hexdigest()
                bounds = box_of({"polygon": polygon})
                previous = next((entry for entry in cache if entry["sha256"] == digest and entry["size"] == crop.size
                                 and entry["mode"] == crop.mode and overlap(entry["box"], bounds) >= .9), None)
                if previous:
                    text, truncated = previous["text"], previous["truncated"]
                    reused += 1
                else:
                    t = time.perf_counter(); text, truncated = engine.recognizer.predict(crop); timings["recognition"] += (time.perf_counter()-t)*1000
                    cache.append({"sha256": digest, "size": crop.size, "mode": crop.mode,
                                  "box": bounds, "text": text, "truncated": truncated})
                line = {"text": text, "polygon": polygon, "geometry_source": "vietocr_ocr", "hit_decoder_limit": truncated}
                if SIGNATURE.match(match_text(text)) or any(covered_by(bounds, box) >= .85 for box in signature_boxes):
                    line["metadata_excluded_reason"] = "electronic_signature"
                lines.append(line)
                if not line.get("metadata_excluded_reason") and BODY.match(match_text(text)):
                    break
            t = time.perf_counter(); status = assess_header(lines, image.height, full_height); timings["selection"] += (time.perf_counter()-t)*1000
            attempts.append({"source": "vietocr_ocr", "roi": roi, "detected_lines": len(polygons), "recognized_lines": len(lines),
                             "reused_lines": reused, "line_limit_reached": capped, **status})
            final_lines = lines
            if status["header_complete"]:
                break
        return result_record(filename, source_count, final_lines, full_width, full_height, attempts[-1]["roi"],
                             "raster_pixels", True, status, attempts, native_attempts, timings, started)
    finally:
        if document is not None:
            document.close()


def result_record(filename, source_count, lines, width, height, roi, coordinates, used_ocr,
                  status, attempts, native_attempts, timings, started):
    lines = [{**line, "line_index": index} for index, line in enumerate(lines, 1)]
    reasons = ["metadata_from_partial_header_requires_review"]
    if status["missing"]:
        reasons.append("missing_header_evidence:" + ",".join(status["missing"]))
    if not status["body_boundary_seen"]:
        reasons.append("subject_end_not_confirmed")
    if any(line.get("metadata_excluded_reason") for line in lines):
        reasons.append("electronic_signature_excluded_from_metadata")
    limit = not status["header_complete"]
    if limit:
        reasons.append("bounded_first_page_roi_limit_reached")
    timings = {key: round(value, 3) for key, value in timings.items()}
    timings["total"] = round((time.perf_counter()-started)*1000, 3)
    text = "\n".join(line["text"] for line in lines)
    return {"filename": Path(filename).name, "method": "metadata_fast", "partial_result": True,
            "source": "header_ocr" if used_ocr else "header_native_text", "used_ocr": used_ocr,
            "engine": "PaddleOCR Detection + VietOCR B ONNX (header ROI)" if used_ocr else "PyMuPDF (header evidence only)",
            "model": "phase4_exp_b_width1024" if used_ocr else None,
            "detection_model": "PP-OCRv6_medium_det" if used_ocr else None,
            "recognition_provider": "CPUExecutionProvider" if used_ocr else None,
            "source_page_count": source_count, "page_count": 1, "inspected_pages": [1],
            "processed_pages": [1] if used_ocr else [], "line_count": len(lines),
            "decoder_limit_hits": sum(bool(line.get("hit_decoder_limit")) for line in lines),
            "pages": [{"page": 1, "width": width, "height": height, "coordinate_system": coordinates,
                       "roi": roi, "lines": lines, "text": text}], "text": text,
            "fast_metadata": {"strategy": "bounded_first_page_header_v1", "header_complete": status["header_complete"],
                              "needs_review": True, "reasons": reasons, "roi_limit_reached": limit,
                              "native_header_usable": not used_ocr, "roi_attempts": attempts,
                              "native_header_attempts": native_attempts},
            "timings_ms": timings, "elapsed_ms": round(timings["total"]), "deployment_approved": False,
            "limitations": ["Partial first-page header only; remaining source pages were not OCRed",
                            "Unknown fields remain unknown; no spelling or diacritic correction",
                            "Upright administrative layouts only; review stamps and incomplete/overlapping headers"]}

"""Experimental per-line PDF/OCR source selection, without changing raw OCR.

H1 uses the frozen v1 trust gates only when explicitly selected by the caller.
It never invokes inference, changes model preprocessing, or reads labels. Each
output line carries its original OCR text and the reason for any fallback.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import time
from collections import Counter

from .contract import MAX_IMAGE_PIXELS, MAX_PDF_PAGES, validate_upload
from .hybrid_gates import (
    GATES, assemble, assign_words, base_font_name, covered_words, dark_mask,
    font_trust, ink_checks, iou, normalized_distance, unicode_problem,
)

VERSION = "h1_v1"
FILLED, STROKED, CLIPPED = 16, 32, 64
SUPERSCRIPT = 1
REASONS = (
    "page_unsupported_geometry", "page_word_segmentation_mismatch", "page_no_text_layer", "page_hidden_text_layer",
    "no_text_layer_words", "word_straddles_polygon", "ambiguous_word_assignment", "multi_line_text",
    "duplicate_text", "overlapping_text", "word_shared_between_polygons",
    "invisible_text", "covered_text", "clipped_text", "superscript_text", "untrusted_font_mapping",
    "replacement_character", "control_or_unassigned_character", "orphan_combining_mark", "non_latin_letter",
    "out_of_vocabulary_character", "word_without_ink", "unexplained_ink",
    "token_count_differs_from_b1024", "gross_mismatch_with_b1024",
)
# Resource guards, separate from the frozen accuracy gates. Dense or pathological
# text layers keep OCR instead of making the opt-in feature expensive.
MAX_H1_XREFS = 50_000
MAX_H1_WORDS = 2_000
MAX_H1_CHARS = 30_000
MAX_H1_LINES = 1_500
MAX_H1_DRAW_ITEMS = 8_000

def document_fonts(doc) -> list[dict]:
    """Every font object of the document (page content, form XObjects and widget appearances)."""
    fonts = []
    for xref in range(1, doc.xref_length()):
        try:
            if doc.xref_get_key(xref, "Type") != ("name", "/Font"):
                continue
            subtype = doc.xref_get_key(xref, "Subtype")[1].lstrip("/")
            basefont = doc.xref_get_key(xref, "BaseFont")
            kind, value = doc.xref_get_key(xref, "Encoding")
            tounicode = doc.xref_get_key(xref, "ToUnicode")[0] != "null"
        except Exception:  # noqa: BLE001 - damaged object: it simply earns no trust
            continue
        if subtype.startswith("CIDFontType"):
            continue  # descendant of a Type0 font, which carries the encoding and ToUnicode
        fonts.append({"xref": xref, "type": subtype, "basefont": basefont[1].lstrip("/") if basefont[0] == "name" else "",
                      "encoding": value.lstrip("/") if kind == "name" else ("" if kind == "null" else "custom"),
                      "has_tounicode": tounicode})
    return fonts


def page_words(page) -> tuple[list[tuple], list[dict]]:
    """Words split on whitespace inside each MuPDF line, with the attributes of their spans.

    Word tuples follow PyMuPDF's (x0, y0, x1, y1, text, block, line, word) plus their index.
    """
    words, attributes = [], []
    raw = page.get_text("rawdict")
    for block_no, block in enumerate(raw["blocks"]):
        if block.get("type") != 0:
            continue
        for line_no, line in enumerate(block["lines"]):
            current: list[tuple[dict, dict]] = []
            word_no = 0

            def flush():
                nonlocal word_no
                if not current:
                    return
                boxes = [c["bbox"] for c, _ in current]
                spans = [s for _, s in current]
                words.append((min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes),
                              max(b[3] for b in boxes), "".join(c["c"] for c, _ in current), block_no, line_no,
                              word_no, len(words)))
                attributes.append({
                    "chars": len(current),
                    "fonts": sorted({s["font"] for s in spans}),
                    "invisible": any(not s["char_flags"] & (FILLED | STROKED) or s["alpha"] == 0 for s in spans),
                    "clipped": any(s["char_flags"] & CLIPPED for s in spans),
                    "superscript": any(s["flags"] & SUPERSCRIPT for s in spans),
                })
                word_no += 1

            for span in line["spans"]:
                for char in span["chars"]:
                    if char["c"].isspace():
                        flush()
                        current = []
                    else:
                        current.append((char, span))
            flush()
    return words, attributes


def polygon_box(polygon: list) -> tuple[float, float, float, float]:
    xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def scale(box, factor: float) -> tuple:
    return tuple(v * factor for v in box[:4])


# ------------------------------------------------------------- decisions

def decide_page(page, rgb, a0_page: dict, zoom: float, trust: dict[str, bool], vocabulary: set[str] | None) -> tuple[dict, list[dict]]:
    """Page record and one decision per A0 line (same order). Reads nothing but the PDF page and A0."""
    started = time.perf_counter()
    words, attributes = page_words(page)
    covered = covered_words(words, page.get_bboxlog())
    for index in covered:
        attributes[index]["covered"] = True
    hidden = {i for i, a in enumerate(attributes) if a["invisible"] or a.get("covered")}
    total_chars = sum(a["chars"] for a in attributes)
    hidden_chars = sum(attributes[i]["chars"] for i in hidden)
    words_text_check = Counter(w[4] for w in page.get_text("words", sort=False)) == Counter(w[4] for w in words)
    geometry_ok = page.rotation == 0 and tuple(page.cropbox) == tuple(page.mediabox)
    dark = dark_mask(rgb)
    visible_boxes_px = [scale(w, zoom) for i, w in enumerate(words) if i not in hidden]

    boxes_pt = [scale(polygon_box(line["polygon"]), 1 / zoom) for line in a0_page["lines"]]
    owners = Counter()
    assigned = []
    for box in boxes_pt:
        inside, problem = assign_words(words, box)
        assigned.append((inside, problem))
        owners.update(w[8] for w in inside)
    covered_lines = sum(any(w[8] not in hidden for w in inside) for inside, _ in assigned)
    lines = len(a0_page["lines"])
    if not geometry_ok:
        page_class, page_reason = "unsupported_geometry", "page_unsupported_geometry"
    elif not words_text_check:
        page_class, page_reason = "word_segmentation_mismatch", "page_word_segmentation_mismatch"
    elif total_chars == 0:
        page_class, page_reason = "no_text_layer", "page_no_text_layer"
    elif hidden_chars / total_chars >= GATES["hidden_min_share"]:
        page_class, page_reason = "hidden_text_layer", "page_hidden_text_layer"
    elif (total_chars - hidden_chars >= GATES["native_min_visible_chars"]
          and lines and covered_lines / lines >= GATES["native_min_line_coverage"]):
        page_class, page_reason = "native_text", None
    else:
        page_class, page_reason = "partial_text", None

    decisions = []
    for line, box_pt, (inside, problem) in zip(a0_page["lines"], boxes_pt, assigned):
        b1024 = line["text"]
        failed, checks = [], {"words": len(inside)}
        if page_reason:
            failed.append(page_reason)
        if not inside:
            failed.append("no_text_layer_words")
        if problem:
            failed.append(problem)
        if any(owners[w[8]] > 1 for w in inside):
            failed.append("word_shared_between_polygons")
        pdf_text, deviation = None, None
        if inside:
            attrs = [attributes[w[8]] for w in inside]
            if any(a["invisible"] for a in attrs):
                failed.append("invisible_text")
            if any(a.get("covered") for a in attrs):
                failed.append("covered_text")
            if any(a["clipped"] for a in attrs):
                failed.append("clipped_text")
            if GATES["reject_superscript"] and any(a["superscript"] for a in attrs):
                failed.append("superscript_text")
            fonts = sorted({f for a in attrs for f in a["fonts"]})
            untrusted = [f for f in fonts if not trust.get(base_font_name(f), False)]
            if untrusted:
                failed.append("untrusted_font_mapping")
            pdf_text, stream_differs = assemble(inside)
            why = unicode_problem(pdf_text, vocabulary)
            if why:
                failed.append(why)
            polygon_px = polygon_box(line["polygon"])
            blank, unexplained = ink_checks(dark, [scale(w, zoom) for w in inside], [a["chars"] for a in attrs],
                                            visible_boxes_px, polygon_px)
            if blank:
                failed.append("word_without_ink")
            if unexplained > GATES["max_unexplained_ink_share"]:
                failed.append("unexplained_ink")
            tokens = (len(pdf_text.split()), len(b1024.split()))
            if GATES["require_same_token_count"] and tokens[0] != tokens[1]:
                failed.append("token_count_differs_from_b1024")
            distance = normalized_distance(pdf_text, b1024)
            if distance > GATES["max_distance_to_b1024"]:
                failed.append("gross_mismatch_with_b1024")
            union = (min(w[0] for w in inside), min(w[1] for w in inside), max(w[2] for w in inside), max(w[3] for w in inside))
            union_px = scale(union, zoom)
            deviation = {"iou": round(iou(union_px, polygon_px), 4),
                         "offset_px": [round(union_px[i] - polygon_px[i], 1) for i in range(4)]}
            checks.update({"fonts": fonts, "untrusted_fonts": untrusted, "stream_order_differs": stream_differs,
                           "words_without_ink": len(blank), "unexplained_ink_share": round(unexplained, 4),
                           "tokens_pdf_b1024": list(tokens), "distance_to_b1024": round(distance, 4)})
        failed = sorted(set(failed), key=REASONS.index)
        decisions.append({
            "line_index": line["line_index"], "source": "b1024" if failed else "pdf_text",
            "fallback_reason": failed[0] if failed else None, "failed_gates": failed,
            "b1024_text": b1024, "pdf_text": pdf_text, "text": b1024 if failed else pdf_text,
            "bbox": [round(v, 1) for v in polygon_box(line["polygon"])], "text_layer_deviation": deviation,
            "checks": checks,
        })
    record = {
        "page": a0_page["page"], "class": page_class, "rotation": page.rotation, "zoom": round(zoom, 6),
        "text_layer_chars": total_chars, "hidden_chars": hidden_chars, "words": len(words),
        "covered_words": len(covered), "words_text_matches_pymupdf": words_text_check,
        "lines": lines, "lines_with_visible_words": covered_lines,
        "visible_words_outside_every_polygon": sum(1 for w in words if w[8] not in hidden and not owners[w[8]]),
        "selected": sum(d["source"] == "pdf_text" for d in decisions),
        "h1_decide_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    return record, decisions



def _validate_result(result: dict, page_count: int) -> None:
    if not isinstance(result, dict) or result.get("method") != "vietocr_ocr":
        raise ValueError("H1 cần kết quả OCR gốc.")
    pages = result.get("pages")
    if not isinstance(pages, list) or len(pages) != page_count:
        raise ValueError("Số trang OCR không khớp tài liệu.")
    for number, page in enumerate(pages, 1):
        if not isinstance(page, dict) or page.get("page") != number:
            raise ValueError("Thứ tự trang OCR không hợp lệ.")
        width, height = page.get("width"), page.get("height")
        if (type(width) is not int or type(height) is not int or width < 1 or height < 1
                or width * height > MAX_IMAGE_PIXELS + 5000):
            raise ValueError("Kích thước trang OCR không hợp lệ.")
        lines = page.get("lines")
        if not isinstance(lines, list):
            raise ValueError("Danh sách dòng OCR không hợp lệ.")
        ids = set()
        for line in lines:
            if not isinstance(line, dict) or not isinstance(line.get("text"), str):
                raise ValueError("Dòng OCR không hợp lệ.")
            index = line.get("line_index")
            if type(index) is not int or index < 1 or index in ids:
                raise ValueError("Chỉ số dòng OCR không hợp lệ.")
            ids.add(index)
            polygon = line.get("polygon")
            if (not isinstance(polygon, list) or len(polygon) != 4
                    or any(not isinstance(point, list) or len(point) != 2 for point in polygon)
                    or any(type(value) not in (int, float) or not math.isfinite(value)
                           for point in polygon for value in point)
                    or any(not (0 <= x <= width and 0 <= y <= height) for x, y in polygon)):
                raise ValueError("Vùng dòng OCR không hợp lệ.")
            area = abs(sum(polygon[i][0] * polygon[(i + 1) % 4][1]
                           - polygon[(i + 1) % 4][0] * polygon[i][1] for i in range(4))) / 2
            if area < 4:
                raise ValueError("Vùng dòng OCR quá nhỏ.")
        if page.get("text") != "\n".join(line["text"] for line in lines):
            raise ValueError("Văn bản trang OCR không khớp các dòng gốc.")
    if result.get("text") != "\n\n".join(page["text"] for page in pages):
        raise ValueError("Văn bản OCR không khớp các trang gốc.")


def _fallback_page(page: dict, reason: str) -> tuple[dict, list[dict]]:
    return (
        {"page": page["page"], "class": "fallback", "selected": 0, "fallback_reason": reason},
        [{"line_index": line["line_index"], "text": line["text"], "b1024_text": line["text"],
          "source": "b1024", "fallback_reason": reason, "failed_gates": [reason]}
         for line in page["lines"]],
    )


def apply_hybrid_h1(content: bytes, filename: str, ocr_result: dict, *,
                    vocabulary: set[str] | None = None) -> dict:
    """Return an independent experimental result; the OCR input is never mutated.

    Unsupported geometry, missing visibility metadata and resource limits fall
    back to the original line text. Invalid uploads or inconsistent OCR geometry
    are rejected, so PDF text cannot be attached to the wrong source coordinates.
    """
    if validate_upload(filename, content) != ".pdf":
        raise ValueError("H1 thử nghiệm chỉ hỗ trợ PDF.")
    import fitz
    import numpy as np

    from .engine import iter_images

    started = time.perf_counter()
    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception as error:
        raise ValueError("PDF không thể đọc được hoặc đã hỏng.") from error
    with doc:
        if doc.needs_pass:
            raise ValueError("PDF được bảo vệ bằng mật khẩu; hãy cung cấp bản không khóa.")
        if not 1 <= len(doc) <= MAX_PDF_PAGES:
            raise ValueError(f"Demo hỗ trợ tối đa {MAX_PDF_PAGES} trang PDF mỗi lần.")
        _validate_result(ocr_result, len(doc))
        result = copy.deepcopy(ocr_result)
        document_limit = doc.xref_length() > MAX_H1_XREFS
        trust = {} if document_limit else font_trust(document_fonts(doc))
        native_lines = 0
        ocr_lines = 0
        rasters = iter_images(content, ".pdf")
        try:
            for source_page, output_page in zip(doc, result["pages"]):
                page_number, image = next(rasters)
                if ((image.width, image.height) != (output_page["width"], output_page["height"])
                        or page_number != output_page["page"]):
                    raise ValueError("Kích thước render không khớp trang OCR gốc.")
                if document_limit:
                    record, decisions = _fallback_page(output_page, "document_text_limit")
                elif (source_page.rotation != 0
                      or tuple(source_page.cropbox) != tuple(source_page.mediabox)):
                    record, decisions = _fallback_page(output_page, "page_unsupported_geometry")
                else:
                    try:
                        words = source_page.get_text("words", sort=False)
                        if (len(words) > MAX_H1_WORDS
                                or sum(len(word[4]) for word in words) > MAX_H1_CHARS
                                or len(output_page["lines"]) > MAX_H1_LINES
                                or len(source_page.get_bboxlog()) > MAX_H1_DRAW_ITEMS):
                            record, decisions = _fallback_page(output_page, "page_text_limit")
                        else:
                            rect = source_page.rect
                            zoom = min(2.0, math.sqrt(MAX_IMAGE_PIXELS / (rect.width * rect.height)))
                            record, decisions = decide_page(
                                source_page, np.asarray(image), output_page, zoom, trust, vocabulary)
                    except (RuntimeError, ValueError, KeyError, TypeError, OverflowError):
                        # Some PDF backends do not expose the visibility evidence H1
                        # requires. Missing evidence never earns native-text trust.
                        record, decisions = _fallback_page(output_page, "page_text_unavailable")
                for line, decision in zip(output_page["lines"], decisions):
                    native = decision["source"] == "pdf_text"
                    original = line["text"]
                    line.update({
                        "text": decision["text"] if native else original,
                        "ocr_text": original,
                        "text_source": "pdf_text" if native else "ocr",
                        "fallback_reason": decision["fallback_reason"],
                        "failed_gates": decision["failed_gates"],
                    })
                    native_lines += int(native)
                    ocr_lines += int(not native)
                output_page["text"] = "\n".join(line["text"] for line in output_page["lines"])
                output_page["h1_page"] = record
        finally:
            rasters.close()
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    result.update({
        "method": "hybrid_h1",
        "source": "trusted_pdf_text_or_ocr",
        "engine": "H1 experimental + " + str(ocr_result.get("engine", "VietOCR B1024")),
        "text": "\n\n".join(page["text"] for page in result["pages"]),
        "experimental": True,
        "deployment_approved": False,
        "h1": {
            "version": VERSION,
            "gates_sha256": hashlib.sha256(json.dumps(GATES, sort_keys=True).encode("utf-8")).hexdigest(),
            "native_lines": native_lines,
            "ocr_lines": ocr_lines,
            "elapsed_ms": elapsed_ms,
        },
    })
    result["limitations"] = list(ocr_result.get("limitations", [])) + [
        "H1 is experimental; field and scan accuracy require independent evaluation",
        "Every PDF text selection retains its original OCR text and source provenance",
    ]
    if type(ocr_result.get("elapsed_ms")) in (int, float):
        result["elapsed_ms"] = ocr_result["elapsed_ms"] + elapsed_ms
    return result

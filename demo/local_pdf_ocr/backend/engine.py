"""Local end-to-end OCR: PDF/image -> PaddleOCR v6 detection -> frozen VietOCR B ONNX.

- One page at a time, CPU-only ONNX Runtime for the first Windows demo.
- No spelling corrections, dictionary replacements, training, or blind-test reads.
- No external requests by this module other than PaddleOCR's first-run model fetch.
- NO assumption that detection, crop or reading order matches earlier recognizer parity.
"""
from __future__ import annotations

import io
import math
import time
from pathlib import Path

from .contract import (
    MAX_IMAGE_PIXELS, MAX_PDF_PAGES, MODEL_DIR,
    decode_ids, validate_upload, verify_frozen_onnx,
)


def resize_width(width: int, height: int, out_h: int = 32, low: int = 32, high: int = 1024) -> int:
    if width < 1 or height < 1:
        raise ValueError("Crop dimensions must be positive")
    return max(low, min(high, math.ceil((int(out_h * width / height)) / 10) * 10))


def vietocr_tensor(rgb_image, metadata):
    """Reproduce pinned vietocr.tool.translate.process_input using PIL+NumPy.

    PIL RGB, LANCZOS, ceil-to-10 width, clamp32..1024, CHW float32 /255.
    Input is one already-rectified line crop.
    """
    import numpy as np
    from PIL import Image

    source = rgb_image.convert("RGB")
    w, h = source.size
    out_height = metadata["image_height"]
    target_w = resize_width(w, h, out_height, metadata["image_min_width"], metadata["image_max_width"])
    resized = source.resize((target_w, out_height), Image.Resampling.LANCZOS)
    chw = np.asarray(resized).transpose(2, 0, 1)
    chw = (chw / 255).astype(np.float32)
    return chw[None, ...]


def sort_detected_polygons(polygons: list) -> list:
    """Top-to-bottom then left-to-right. Limitations: complex columns/tables."""
    def anchor(quad):
        return min(point[1] for point in quad), min(point[0] for point in quad)
    return sorted(polygons, key=anchor)


def iter_images(raw: bytes, extension: str):
    """Yield (one-based page, PIL RGB image) without ever touching disk."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    if extension == ".pdf":
        import fitz

        try:
            pdf = fitz.open(stream=raw, filetype="pdf")
        except Exception as error:
            raise ValueError("PDF không thể đọc được hoặc đã hỏng.") from error
        try:
            if pdf.needs_pass:
                raise ValueError("PDF được bảo vệ bằng mật khẩu; hãy cung cấp bản không khóa.")
            if not 1 <= len(pdf) <= MAX_PDF_PAGES:
                raise ValueError(f"Demo hỗ trợ tối đa {MAX_PDF_PAGES} trang PDF mỗi lần.")
            for index, page in enumerate(pdf):
                rect = page.rect
                if rect.width <= 0 or rect.height <= 0:
                    raise ValueError("Trang PDF có kích thước không hợp lệ.")
                zoom = min(2.0, math.sqrt(MAX_IMAGE_PIXELS / (rect.width * rect.height)))
                if zoom <= 0:
                    raise ValueError("Trang PDF không thể render an toàn.")
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csRGB, alpha=False)
                if pix.width * pix.height > MAX_IMAGE_PIXELS + 5000:
                    raise ValueError("Trang PDF vượt giới hạn pixel.")
                yield index + 1, Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        finally:
            pdf.close()
        return

    try:
        with Image.open(io.BytesIO(raw)) as image:
            # Reject oversized compressed images BEFORE EXIF transposition or
            # pixel decode allocates memory. The demo must remain local-safe.
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ValueError("Ảnh vượt giới hạn 12 triệu pixel.")
            upright = ImageOps.exif_transpose(image)
            yield 1, upright.convert("RGB")
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("Không thể mở ảnh hoặc tệp đã hỏng.") from error


class OnnxVietocrB:
    def __init__(self, metadata: dict):
        import onnxruntime as ort

        self.metadata = metadata
        # CPUExecutionProvider is explicit: don't claim verified GPU placement.
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        self.encoder = ort.InferenceSession(
            str(MODEL_DIR / "encoder.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self.decoder = ort.InferenceSession(
            str(MODEL_DIR / "decoder_step.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        if (self.encoder.get_inputs()[0].name != "image"
                or {input_.name for input_ in self.decoder.get_inputs()} != {"tokens", "memory"}):
            raise RuntimeError("Unexpected frozen ONNX input signature")

    def predict(self, image):
        import numpy as np

        pixels = vietocr_tensor(image, self.metadata)
        memory = self.encoder.run(["memory"], {"image": pixels})[0]
        ids = [1]
        for _ in range(self.metadata["decoder_max_seq_length"] + 1):
            prefix = np.asarray(ids, dtype=np.int64).reshape(-1, 1)
            logits = self.decoder.run(["logits"], {"tokens": prefix, "memory": memory})[0]
            if logits.shape != (1, self.metadata["vocab_size"]) or not np.isfinite(logits).all():
                raise RuntimeError("Invalid ONNX decoder logits")
            token = int(np.argmax(logits[0]))
            ids.append(token)
            if token == 2:
                break
        return decode_ids(ids, self.metadata["vocab"]), ids[-1] != 2


class PaddleTextDetector:
    def __init__(self):
        import cv2
        from paddleocr import TextDetection
        from paddlex.inference.pipelines.components import CropByPolys

        self.cv2 = cv2
        self.detector = TextDetection(model_name="PP-OCRv6_medium_det", device="cpu")
        self.cropper = CropByPolys(det_box_type="quad")

    def detect_and_crop(self, page_image):
        import numpy as np
        from PIL import Image

        bgr = self.cv2.cvtColor(np.asarray(page_image), self.cv2.COLOR_RGB2BGR)
        detections = list(self.detector.predict(bgr, batch_size=1))
        if len(detections) != 1:
            raise RuntimeError(f"Expected one detection result; got {len(detections)}")
        item = detections[0]
        payload = item.json["res"] if hasattr(item, "json") else item
        polygons = payload.get("dt_polys")
        if polygons is None:
            raise RuntimeError("Paddle TextDetection result missing dt_polys")
        bounded = []
        for poly in polygons:
            p = np.asarray(poly, dtype=np.float32)
            if p.shape != (4, 2) or not np.isfinite(p).all():
                raise RuntimeError("Invalid text detection quadrilateral")
            p[:, 0] = np.clip(p[:, 0], 0, page_image.width - 1)
            p[:, 1] = np.clip(p[:, 1], 0, page_image.height - 1)
            if self.cv2.contourArea(p) < 4:
                continue
            bounded.append(p.tolist())
        ordered = sort_detected_polygons(bounded)
        for quad in ordered:
            crop_bgr = self.cropper(bgr, [quad])[0]
            if crop_bgr is None or crop_bgr.size == 0:
                raise RuntimeError("PaddleX CropByPolys returned an empty text crop")
            if crop_bgr.ndim != 3 or crop_bgr.shape[2] != 3:
                raise RuntimeError("Unexpected crop BGR shape")
            crop_rgb = self.cv2.cvtColor(crop_bgr, self.cv2.COLOR_BGR2RGB)
            yield quad, Image.fromarray(crop_rgb)


class LocalOcrEngine:
    def __init__(self):
        metadata = verify_frozen_onnx(require_weights=True)
        self.recognizer = OnnxVietocrB(metadata)
        self.detector = PaddleTextDetector()
        self.checkpoint_sha256 = metadata["checkpoint_sha256"]

    def process(self, source: bytes, filename: str) -> dict:
        extension = validate_upload(filename, source)
        started = time.perf_counter()
        pages = []
        all_text = []
        limit_hits = 0
        for number, image in iter_images(source, extension):
            page_started = time.perf_counter()
            recognized = []
            for i, (polygon, crop) in enumerate(self.detector.detect_and_crop(image), start=1):
                text, truncated = self.recognizer.predict(crop)
                limit_hits += int(truncated)
                recognized.append({
                    "line_index": i,
                    "polygon": polygon,
                    "text": text,
                    "hit_decoder_limit": truncated,
                })
            page_text = "\n".join(item["text"] for item in recognized)
            pages.append({
                "page": number,
                "width": image.width,
                "height": image.height,
                "lines": recognized,
                "text": page_text,
                "elapsed_ms": round((time.perf_counter() - page_started) * 1000),
            })
            all_text.append(page_text)
        return {
            "filename": Path(filename).name,
            "model": "phase4_exp_b_width1024",
            "detection_model": "PP-OCRv6_medium_det",
            "recognition_provider": "CPUExecutionProvider",
            "page_count": len(pages),
            "line_count": sum(len(item["lines"]) for item in pages),
            "decoder_limit_hits": limit_hits,
            "pages": pages,
            "text": "\n\n".join(all_text),
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "limitations": [
                "Document orientation and text-line 180-degree classification are not included",
                "Basic top-to-bottom order; complex columns/tables need separate layout evaluation",
                "Detector + crop + PDF rendering have NOT passed end-to-end regression",
                "No spelling or diacritic corrections are applied",
            ],
            "deployment_approved": False,
        }

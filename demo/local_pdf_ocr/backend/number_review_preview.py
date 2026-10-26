"""Render an original-document crop for human review, without OCR or persistence."""
from __future__ import annotations

import io
import json
import math
from contextlib import closing

from .contract import MAX_IMAGE_PIXELS, MAX_PDF_PAGES, validate_upload
from .engine import iter_images

MAX_POLYGON_JSON_BYTES = 2048
MAX_REVIEW_PIXELS = 2_000_000
CONTEXT_PIXELS = 12


def _positive_integer(value, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{label} phải là số nguyên dương.")
    return value


def _validate_polygon(polygon) -> list[list[float]]:
    if not isinstance(polygon, list) or len(polygon) != 4:
        raise ValueError("Vùng đối chiếu phải có bốn góc.")
    def finite_number(value):
        try:
            return (isinstance(value, (int, float)) and not isinstance(value, bool)
                    and math.isfinite(value))
        except OverflowError:
            return False

    if any(
        not isinstance(point, list) or len(point) != 2
        or any(not finite_number(value) for value in point)
        for point in polygon
    ):
        raise ValueError("Tọa độ vùng đối chiếu không hợp lệ.")
    quad = [[float(value) for value in point] for point in polygon]
    # Detector quads are convex and ordered around their boundary. Reject a
    # crossing or collapsed request rather than suggesting a misleading crop.
    crosses = []
    for index in range(4):
        a, b, c = (quad[(index + offset) % 4] for offset in range(3))
        crosses.append((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]))
    area = abs(sum(quad[i][0] * quad[(i + 1) % 4][1]
                   - quad[(i + 1) % 4][0] * quad[i][1] for i in range(4))) / 2
    if area < 4 or not (all(value > 0 for value in crosses) or all(value < 0 for value in crosses)):
        raise ValueError("Vùng đối chiếu bị rỗng hoặc có hình học không hợp lệ.")
    return quad


def parse_preview_polygon(polygon_json: str) -> list[list[float]]:
    """Parse the small form field independently of upload or model handling."""
    try:
        valid_size = isinstance(polygon_json, str) and len(polygon_json.encode("utf-8")) <= MAX_POLYGON_JSON_BYTES
    except UnicodeError:
        valid_size = False
    if not valid_size:
        raise ValueError("Yêu cầu vùng đối chiếu quá lớn hoặc không hợp lệ.")
    try:
        polygon = json.loads(polygon_json)
    except (ValueError, TypeError, RecursionError) as error:
        raise ValueError("Không đọc được tọa độ vùng đối chiếu.") from error
    return _validate_polygon(polygon)


def render_number_review_preview(payload: bytes, filename: str, *, page: int,
                                 polygon: list, render_width: int, render_height: int) -> bytes:
    """Return a bounded PNG in the same raster coordinate system as main OCR.

    The caller supplies the original upload and OCR page dimensions. A stale or
    mismatched page is rejected; no text is inferred, replaced or saved.
    """
    if not isinstance(payload, bytes):
        raise ValueError("Nội dung tài liệu không hợp lệ.")
    extension = validate_upload(filename, payload)
    _positive_integer(page, "Số trang")
    if page > MAX_PDF_PAGES or (extension != ".pdf" and page != 1):
        raise ValueError("Trang đối chiếu không tồn tại trong tài liệu.")
    width = _positive_integer(render_width, "Chiều rộng trang OCR")
    height = _positive_integer(render_height, "Chiều cao trang OCR")
    # Match the renderer's allowance for PDF pixel rounding at the 12 MP cap.
    if width * height > MAX_IMAGE_PIXELS + 5000:
        raise ValueError("Kích thước trang đối chiếu vượt giới hạn pixel.")
    quad = _validate_polygon(polygon)
    xs, ys = [point[0] for point in quad], [point[1] for point in quad]
    if min(xs) < 0 or min(ys) < 0 or max(xs) > width or max(ys) > height:
        raise ValueError("Vùng đối chiếu nằm ngoài trang OCR.")
    if max(xs) - min(xs) < 2 or max(ys) - min(ys) < 2:
        raise ValueError("Vùng đối chiếu quá nhỏ.")
    bounds = (max(0, math.floor(min(xs)) - CONTEXT_PIXELS),
              max(0, math.floor(min(ys)) - CONTEXT_PIXELS),
              min(width, math.ceil(max(xs)) + CONTEXT_PIXELS),
              min(height, math.ceil(max(ys)) + CONTEXT_PIXELS))
    if (bounds[2] - bounds[0]) * (bounds[3] - bounds[1]) > MAX_REVIEW_PIXELS:
        raise ValueError("Vùng đối chiếu quá lớn; hãy xem trang gốc.")
    from PIL import Image

    try:
        with closing(iter_images(payload, extension)) as pages:
            image = next((image for number, image in pages if number == page), None)
    except Image.DecompressionBombError as error:
        raise ValueError("Ảnh vượt giới hạn pixel.") from error
    if image is None:
        raise ValueError("Kích thước trang gốc không khớp kết quả OCR; hãy xử lý lại tài liệu.")
    try:
        if image.size != (width, height):
            raise ValueError("Kích thước trang gốc không khớp kết quả OCR; hãy xử lý lại tài liệu.")
        with image.crop(bounds) as crop:
            data = io.BytesIO()
            crop.save(data, format="PNG")
            return data.getvalue()
    finally:
        image.close()

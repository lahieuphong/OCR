"""Read-only original-PDF text-line preview for local OCR review.

Renders the same source-page geometry as OCR, then crops a padded axis-aligned
rectangle for a HUMAN reviewer. No Paddle detector, ONNX inference, text-layer
substitution, automatic corrections, or persistence.
"""
from __future__ import annotations

import io
import json
import math
from contextlib import closing

from .contract import validate_upload
from .engine import iter_images


def create_review_preview(source: bytes, filename: str, *, page: int,
                          width: int, height: int, polygon_json: str) -> bytes:
    ext = validate_upload(filename, source)
    if not isinstance(page, int) or page < 1 or page > 6:
        raise ValueError("Invalid OCR page number")
    if not isinstance(width, int) or not isinstance(height, int) or width < 1 or height < 1:
        raise ValueError("Invalid OCR page pixel dimensions")
    if not isinstance(polygon_json, str) or len(polygon_json) > 2048:
        raise ValueError("Invalid OCR rectangle request")
    try:
        quad = json.loads(polygon_json)
    except (json.JSONDecodeError, TypeError) as err:
        raise ValueError("Invalid OCR polygon JSON") from err
    if not isinstance(quad, list) or len(quad) != 4:
        raise ValueError("Require a four-corner OCR polygon")
    if any(
        not isinstance(point, list) or len(point) != 2
        or any(not isinstance(n, (int, float)) or isinstance(n, bool)
               or not math.isfinite(n) for n in point)
        for point in quad
    ):
        raise ValueError("Invalid polygon coordinates")
    if ext != ".pdf" and page != 1:
        raise ValueError("An image has only one page")
    with closing(iter_images(source, ext)) as pages:
        image = next((image for index, image in pages if index == page), None)
    if image is None or image.size != (width, height):
        raise ValueError("STOP: review source page size differs from OCR JSON")
    xs = [float(point[0]) for point in quad]
    ys = [float(point[1]) for point in quad]
    if min(xs) < 0 or min(ys) < 0 or max(xs) > width or max(ys) > height:
        raise ValueError("Polygon outside OCR source image")
    if max(xs) - min(xs) < 2 or max(ys) - min(ys) < 2:
        raise ValueError("Empty OCR review polygon")
    left = max(0, math.floor(min(xs)) - 12)
    right = min(width, math.ceil(max(xs)) + 12)
    upper = max(0, math.floor(min(ys)) - 12)
    lower = min(height, math.ceil(max(ys)) + 12)
    crop = image.crop((left, upper, right, lower))
    if crop.width < 2 or crop.height < 2:
        raise ValueError("Empty crop")
    data = io.BytesIO()
    crop.save(data, format="PNG")
    return data.getvalue()

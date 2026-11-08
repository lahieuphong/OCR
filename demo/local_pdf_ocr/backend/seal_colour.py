"""Seal colour from pixels: is there a round red seal on the document? No OCR, no model.

Pages are rendered at a low resolution, starting from the last page, because the signature
page and its seal usually come last or just before the appendices. The search stops at the
first round red mark of an official seal's size. It only reports what the pixels show:

* "found": a red round mark of 22-60 mm was found on a page.
* "black_and_white": every checked page is a black-and-white scan, so a seal's colour cannot be
  known. A PDF page counts as one when the image covering most of it is greyscale: the colour
  of the page itself is not used, since a signing portal can add coloured text to a grey scan.
* "not_found": no red round mark on the checked pages.

Only "found" fills the seal-colour field. Nothing here reads or changes the OCR text.
"""
from __future__ import annotations

import math
import time

from .contract import MAX_FAST_SOURCE_PAGES, MAX_IMAGE_PIXELS

METHOD = "red_round_mark_v1"
DPI = 100
SEAL_MM = (22.0, 60.0)        # official round seals are about 30-50 mm across
ASPECT = (.75, 1.33)
# Convex hull area over bounding box area: a disc gives pi/4 (0.785), a rectangular
# "HỎA TỐC" or arrival stamp gives about 1.
ROUND_FILL = (.68, .88)
TAIL_PAGES = 20               # searched from the last page back
HEAD_PAGES = 20               # then from the first page forward, in long documents
COLOUR_SHARE = 1e-4           # below this share of saturated pixels a page counts as black and white
A4_SHORT_SIDE_MM = 210.0      # an uploaded image has no physical size; it is taken as an A4 page


def page_order(count: int) -> list[int]:
    """Zero-based page indices to check, last page first."""
    tail = list(range(count - 1, max(-1, count - 1 - TAIL_PAGES), -1))
    head = [index for index in range(min(count, HEAD_PAGES)) if index not in tail]
    return tail + head


def masks(rgb):
    import cv2
    import numpy as np

    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    hue, saturation, value = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    coloured = (saturation >= 60) & (value >= 60)
    red = coloured & ((hue <= 10) | (hue >= 170))
    return np.ascontiguousarray(coloured), np.ascontiguousarray(red)


def round_red_marks(rgb, mm_per_pixel: float) -> tuple[list[dict], float]:
    """Round red marks of a seal's size, and the page's share of coloured pixels."""
    import cv2
    import numpy as np

    coloured, red = masks(rgb)
    share = float(coloured.mean())
    if not red.any():
        return [], share
    kernel = max(3, round(2.3 / mm_per_pixel)) | 1          # about 2 mm joins a seal's ring and letters
    joined = cv2.morphologyEx(red.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((kernel, kernel), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(joined, connectivity=8)
    height, width = red.shape
    marks = []
    for label in range(1, count):
        x, y, w, h, _area = (int(v) for v in stats[label])
        w_mm, h_mm = w * mm_per_pixel, h * mm_per_pixel
        if not (SEAL_MM[0] <= w_mm <= SEAL_MM[1] and SEAL_MM[0] <= h_mm <= SEAL_MM[1]
                and ASPECT[0] <= w / h <= ASPECT[1]):
            continue
        points = cv2.findNonZero((labels[y:y + h, x:x + w] == label).astype(np.uint8))
        fill = float(cv2.contourArea(cv2.convexHull(points))) / (w * h)
        if not ROUND_FILL[0] <= fill <= ROUND_FILL[1]:
            continue
        marks.append({"size_mm": [round(w_mm, 1), round(h_mm, 1)], "round_fill": round(fill, 3),
                      "box": [round(x / width, 4), round(y / height, 4), round((x + w) / width, 4), round((y + h) / height, 4)]})
    return marks, share


def greyscale_scan(document, page) -> bool:
    """Is the page a scan whose main image (covering at least half the page) is greyscale?"""
    page_area = page.rect.width * page.rect.height
    largest, covered = None, 0.0
    for item in page.get_images(full=True):
        try:
            area = sum(abs(rect & page.rect) for rect in page.get_image_rects(item[0]))
        except Exception:
            continue
        if area > covered:
            largest, covered = item, area
    if largest is None or covered < .5 * page_area:
        return False
    xref, bits, space = largest[0], largest[4], largest[5]
    if bits == 1 or space in ("DeviceGray", "CalGray"):
        return True
    if space in ("DeviceRGB", "DeviceCMYK", "CalRGB", "Lab"):
        return False
    try:
        return document.extract_image(xref).get("colorspace") == 1
    except Exception:
        return False


def _pdf_pages(raw: bytes):
    import numpy as np
    import pymupdf

    document = pymupdf.open(stream=raw, filetype="pdf")
    try:
        if document.needs_pass or not 1 <= len(document) <= MAX_FAST_SOURCE_PAGES:
            return
        for index in page_order(len(document)):
            page = document[index]
            rect = page.rect
            if rect.width <= 0 or rect.height <= 0:
                continue
            zoom = min(DPI / 72, math.sqrt(MAX_IMAGE_PIXELS / (rect.width * rect.height)))
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csRGB, alpha=False)
            rgb = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3)
            yield index + 1, rgb, 25.4 / (72 * zoom), greyscale_scan(document, page)
    finally:
        document.close()


def _image_pages(raw: bytes, extension: str):
    import numpy as np
    from PIL import Image

    from .engine import iter_images

    _, image = next(iter_images(raw, extension))
    scale = min(1.0, (A4_SHORT_SIDE_MM / 25.4 * DPI) / min(image.size))
    if scale < 1:
        image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.Resampling.BILINEAR)
    rgb = np.asarray(image.convert("RGB"))
    yield 1, rgb, A4_SHORT_SIDE_MM / min(image.size), float(masks(rgb)[0].mean()) < COLOUR_SHARE


def find_seal(raw: bytes, extension: str) -> dict:
    started = time.perf_counter()
    pages = _pdf_pages(raw) if extension == ".pdf" else _image_pages(raw, extension)
    checked, grey, found = [], 0, None
    for number, rgb, mm_per_pixel, greyscale in pages:
        marks, _share = round_red_marks(rgb, mm_per_pixel)
        checked.append(number)
        grey += greyscale
        if marks:
            found = {"page": number, **max(marks, key=lambda mark: mark["size_mm"][0] * mark["size_mm"][1])}
            break
    reason = ("found" if found else "not_checked" if not checked
              else "black_and_white" if grey == len(checked) else "not_found")
    return {"method": METHOD, "reason": reason, "colour": "red" if found else None,
            **(found or {}), "pages_checked": checked, "greyscale_pages": grey,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1)}

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

A seal impression is one ink. A round red mark whose box also holds printed yellow ink (saturation at least
INK_SATURATION, counted beyond the page's own density of it, so that yellowed or tinted paper is not a second ink) of at
least YELLOW_PER_RED of its red is a two-colour print, such as the national emblem (red disc, yellow star, ears of rice
and cogwheel) on a cover template in an appendix: it is not a seal, is listed in "rejected_marks", and the search goes
on. (Round 6, 2026-11-10: on every page of the 35 PDFs of the gold rounds, the 30 seal marks measure 0.000 and the two
printed emblems 0.868.) Pages are searched in this order: pages named by the caller first (a consolidated text's
authentication block, where its seal is), then the last TAIL_PAGES, the first HEAD_PAGES and, if no seal was found
but a checked page that is not a black-and-white scan shows colour, at most MIDDLE_PAGES of the pages between, from
the end back. A black-and-white scan or a document in black text alone is not searched further.
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
MIDDLE_PAGES = 60             # then, with no seal found but colour seen, the pages between, from the end back
YELLOW_PER_RED = .10          # a mark's yellow ink pixels over its red ones: at or above, a two-colour print, not a seal
INK_SATURATION = 120          # printed yellow or gold ink; yellowed or tinted paper stays well below
COLOUR_SHARE = 1e-4           # below this share of saturated pixels a page counts as black and white
A4_SHORT_SIDE_MM = 210.0      # an uploaded image has no physical size; it is taken as an A4 page


def page_order(count: int, first=()) -> list[int]:
    """Zero-based page indices to check: the caller's pages (1-based numbers in `first`), then last page first."""
    preferred = list(dict.fromkeys(number - 1 for number in first if type(number) is int and 1 <= number <= count))
    tail = [index for index in range(count - 1, max(-1, count - 1 - TAIL_PAGES), -1) if index not in preferred]
    head = [index for index in range(min(count, HEAD_PAGES)) if index not in tail and index not in preferred]
    return preferred + tail + head


def middle_order(count: int, first=()) -> list[int]:
    """The pages page_order leaves out, from the end back, at most MIDDLE_PAGES."""
    seen = set(page_order(count, first))
    return [index for index in range(count - 1, -1, -1) if index not in seen][:MIDDLE_PAGES]


def masks(rgb):
    import cv2
    import numpy as np

    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    hue, saturation, value = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    coloured = (saturation >= 60) & (value >= 60)
    red = coloured & ((hue <= 10) | (hue >= 170))
    # yellow and gold printing ink; orange-red seal ink stays below hue 18, paper below INK_SATURATION
    yellow = (saturation >= INK_SATURATION) & (value >= 60) & (hue >= 18) & (hue <= 40)
    return np.ascontiguousarray(coloured), np.ascontiguousarray(red), np.ascontiguousarray(yellow)


def round_red_marks(rgb, mm_per_pixel: float) -> tuple[list[dict], float, list[dict]]:
    """Round red marks of a seal's size, the page's share of coloured pixels, and the round red marks of a seal's
    size rejected as two-colour prints (module docstring)."""
    import cv2
    import numpy as np

    coloured, red, yellow = masks(rgb)
    share = float(coloured.mean())
    if not red.any():
        return [], share, []
    kernel = max(3, round(2.3 / mm_per_pixel)) | 1          # about 2 mm joins a seal's ring and letters
    joined = cv2.morphologyEx(red.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((kernel, kernel), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(joined, connectivity=8)
    height, width = red.shape
    paper_yellow = float(yellow.mean())  # a tinted page's own yellow is its paper, not a second ink
    marks, rejected = [], []
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
        mark = {"size_mm": [round(w_mm, 1), round(h_mm, 1)], "round_fill": round(fill, 3),
                "box": [round(x / width, 4), round(y / height, 4), round((x + w) / width, 4), round((y + h) / height, 4)]}
        printed = int(yellow[y:y + h, x:x + w].sum()) - paper_yellow * w * h
        yellow_per_red = max(0.0, printed) / max(1, int(red[y:y + h, x:x + w].sum()))
        if yellow_per_red >= YELLOW_PER_RED:
            rejected.append({**mark, "reason": "two_colour_print", "yellow_per_red": round(yellow_per_red, 3)})
        else:
            marks.append(mark)
    return marks, share, rejected


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


def _pdf_pages(raw: bytes, first=(), widen=lambda: False):
    """Pages in the search order; the middle pages only if `widen()` says so once the others are checked."""
    import numpy as np
    import pymupdf

    document = pymupdf.open(stream=raw, filetype="pdf")
    try:
        if document.needs_pass or not 1 <= len(document) <= MAX_FAST_SOURCE_PAGES:
            return
        def order():
            yield from page_order(len(document), first)
            if widen():
                yield from middle_order(len(document), first)
        for index in order():
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


def red_mark_pages(raw: bytes, limit: int) -> list[dict]:
    """PDF pages holding a round red mark of a seal's size, in the search order above, at most `limit`: each with
    its largest mark's box (fractions of the page). Used to find where a scanned document was signed and stamped."""
    found, colour = [], [0]
    widen = lambda: not found and colour[0] > 0  # as find_seal
    for number, rgb, mm_per_pixel, greyscale in _pdf_pages(raw, widen=widen):
        marks, share, _rejected = round_red_marks(rgb, mm_per_pixel)
        colour[0] += not greyscale and share >= COLOUR_SHARE
        if marks:
            found.append({"page": number, **max(marks, key=lambda mark: mark["size_mm"][0] * mark["size_mm"][1])})
            if len(found) >= limit:
                break
    return found


def find_seal(raw: bytes, extension: str, first_pages=()) -> dict:
    """`first_pages`: 1-based page numbers to check before the others (a consolidated text's authentication block)."""
    started = time.perf_counter()
    checked, grey, coloured, found, rejected = [], 0, 0, None, []
    # The middle pages only for a document showing colour: a black-and-white scan's or a black-text document's hold
    # no seal colour either.
    widen = lambda: found is None and coloured > 0
    pages = _pdf_pages(raw, first_pages, widen) if extension == ".pdf" else _image_pages(raw, extension)
    for number, rgb, mm_per_pixel, greyscale in pages:
        marks, share, dropped = round_red_marks(rgb, mm_per_pixel)
        checked.append(number)
        grey += greyscale
        coloured += not greyscale and share >= COLOUR_SHARE
        rejected += [{"page": number, **mark} for mark in dropped]
        if marks:
            found = {"page": number, **max(marks, key=lambda mark: mark["size_mm"][0] * mark["size_mm"][1])}
            break
    reason = ("found" if found else "not_checked" if not checked
              else "black_and_white" if grey == len(checked) else "not_found")
    return {"method": METHOD, "reason": reason, "colour": "red" if found else None,
            **(found or {}), "pages_checked": checked, "greyscale_pages": grey,
            **({"rejected_marks": rejected} if rejected else {}),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1)}

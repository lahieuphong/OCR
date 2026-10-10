"""Opt-in, image-validated header split. Never uses OCR text or edits weights.

Only first-page, broad administrative two-column headings are considered.
Return None on any uncertain geometry; keep the original detection crop.
"""
from __future__ import annotations


def propose_header_split(rgb_image, polygon, *, page_number: int = 1):
    """Return {'polygons':[left,right], 'audit':...} or None (safe fallback).

    Input is the full-resolution PIL RGB page and PaddleOCR quadrilateral in
    top-left, top-right, bottom-right, bottom-left order.
    """
    import numpy as np

    if page_number != 1 or len(polygon) != 4:
        return None
    v = np.asarray(polygon, dtype=np.float64)
    if v.shape != (4, 2) or not np.isfinite(v).all():
        return None
    width, height = rgb_image.size
    if width < 200 or height < 300:
        return None
    x0 = max(0, int(np.floor(v[:, 0].min())))
    y0 = max(0, int(np.floor(v[:, 1].min())))
    x1 = min(width - 1, int(np.ceil(v[:, 0].max())))
    y1 = min(height - 1, int(np.ceil(v[:, 1].max())))
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    if not (.045 * height <= y0 <= .14 * height
            and .68 * width <= bw <= .90 * width
            and .013 * height <= bh <= .045 * height
            and x0 < .23 * width and x1 > .79 * width):
        return None
    if max(abs(v[1, 1] - v[0, 1]), abs(v[2, 1] - v[3, 1])) > .35 * bh:
        return None

    rgb = np.asarray(rgb_image)
    if rgb.ndim != 3 or rgb.shape[2] < 3:
        return None
    gray = rgb[y0:y1 + 1, x0:x1 + 1, :3].astype(np.float32).mean(axis=2)
    ink = (gray < 150).sum(axis=0)
    empty = ink < max(1, int(round(.05 * bh)))
    left_bound = max(x0 + int(.22 * bw), int(.34 * width))
    right_bound = min(x0 + int(.62 * bw), int(.49 * width))
    minimum_gap = max(18, int(round(.015 * width)))
    gaps = []
    start = None
    for i, blank in enumerate(empty):
        if blank and start is None:
            start = i
        if not blank and start is not None:
            gaps.append((start, i - 1))
            start = None
    if start is not None:
        gaps.append((start, len(empty) - 1))
    candidates = []
    for a, b in gaps:
        gx0, gx1 = x0 + a, x0 + b
        center = (gx0 + gx1) / 2.0
        if (b - a + 1 >= minimum_gap
                and left_bound <= center <= right_bound
                and center - x0 >= .22 * bw
                and x1 - center >= .35 * bw):
            candidates.append((b - a + 1, gx0, gx1))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    if len(candidates) > 1 and candidates[1][0] >= .80 * candidates[0][0]:
        return None
    gap_width, gx0, gx1 = candidates[0]
    center = (gx0 + gx1) / 2.0
    left_ink = int(ink[:gx0 - x0].sum())
    right_ink = int(ink[gx1 - x0 + 1:].sum())
    if min(left_ink, right_ink) < 35:
        return None
    top_denom = v[1, 0] - v[0, 0]
    bottom_denom = v[2, 0] - v[3, 0]
    if min(top_denom, bottom_denom) <= 0:
        return None
    ft = (center - v[0, 0]) / top_denom
    fb = (center - v[3, 0]) / bottom_denom
    if not (.15 < ft < .70 and .15 < fb < .70):
        return None
    top = v[0] + ft * (v[1] - v[0])
    bottom = v[3] + fb * (v[2] - v[3])
    left = np.asarray([v[0], top, bottom, v[3]]).astype(int).tolist()
    right = np.asarray([top, v[1], v[2], bottom]).astype(int).tolist()
    return {
        "polygons": [left, right],
        "audit": {
            "algorithm": "header_vertical_ink_gutter_v1",
            "gap_x": round(center, 2),
            "gap_px": gap_width,
            "gap_start_x": gx0,
            "gap_end_x": gx1,
            "dark_pixel_count_left": left_ink,
            "dark_pixel_count_right": right_ink,
            "original_polygon": v.tolist(),
        },
    }

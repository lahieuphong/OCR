"""Deterministic candidate selector for document-number lines.

This is a local QA retrieval heuristic, NOT detection, ground truth, a
classifier or a production correction policy. Never uses reference labels.
Selection may miss badly detected headings; log omissions explicitly.
"""
from __future__ import annotations

import re


# Deliberately restrict to the left-hand document number header, such as
# "Số: 216/TB-VPCP". Do not match references in document body ("... số 216").
NUMBER_HEADER = re.compile(r"^\s*s[ốo]\s*[:.\-]?\s*(?=\S)", re.IGNORECASE)


def is_document_number(row: dict, *, page: int, width: int | None = None,
                       height: int | None = None) -> bool:
    if page != 1:
        return False
    prediction = row.get("ocr_prediction", row.get("text", ""))
    if not isinstance(prediction, str) or not NUMBER_HEADER.search(prediction):
        return False
    polygon = row.get("polygon")
    if not isinstance(polygon, list) or len(polygon) != 4:
        return False
    try:
        xs = [float(p[0]) for p in polygon]
        ys = [float(p[1]) for p in polygon]
    except (ValueError, TypeError, IndexError):
        return False
    # Legacy quality review packs do not retain page dimensions. In that
    # case select only early line indices, never a body citation on line 24.
    # This fallback is explicitly exploratory, not complete field retrieval.
    if width is None or height is None:
        return 1 <= int(row.get("line_index", 999)) <= 18
    if width <= 0 or height <= 0:
        return False
    # Broad layout guard. Số may be in an upper row or below a two-line header.
    if not (0 <= min(xs) < .60 * width and max(xs) <= width * 1.01):
        return False
    if not (.04 * height < min(ys) < .44 * height):
        return False
    if int(row.get("line_index", 999)) > 22:
        return False
    if not (max(ys) - min(ys) < .09 * height):
        return False
    return True


def select_number_headers(page: dict, *, limit: int = 8) -> list[dict]:
    """Return ALL candidates in stable reading order; never pick by correctness."""
    if limit < 1:
        raise ValueError("limit must be >= 1")
    page_n = int(page.get("page", 0))
    width = int(page.get("width", 0))
    height = int(page.get("height", 0))
    rows = [
        r for r in page.get("lines", [])
        if is_document_number(r, page=page_n, width=width, height=height)
    ]
    if len(rows) > limit:
        raise ValueError(
            f"STOP: {len(rows)} potential doc-number lines on page {page_n}; "
            f"limit={limit}. Increase limit to include all; never silently trim."
        )
    return sorted(rows, key=lambda r: r["line_index"])

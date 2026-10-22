"""Conservative geometric reading-order layout for text blocks of PDF pages.

Text itself is preserved verbatim. This only reorders already extracted
blocks from PyMuPDF, and keeps source_block_index for auditability.

Algorithm:
1) Ascending y with 12-PDF-point inter-block vertical gap to form bands.
2) Within each band, attempt left-then-right column traversal ONLY when
   all left blocks are separated from all right blocks by >=6 PDF points;
   otherwise keep top-to-bottom order.

This improves typical administrative-document headers and two-column
signature footers without claiming a universal multi-column layout engine.
"""
from __future__ import annotations


def _position(block: dict) -> tuple[float, float, int]:
    x0, y0, _x1, _y1 = block["bbox"]
    return float(y0), float(x0), block["source_block_index"]


def order_text_blocks(blocks: list[dict], page_width: float, *,
                      band_gap: float = 12.0, column_gap: float = 6.0) -> list[dict]:
    if page_width <= 0:
        raise ValueError("page_width must be positive")
    if not blocks:
        return []
    sorted_blocks = sorted(blocks, key=_position)
    bands: list[list[dict]] = []
    ymax = -float("inf")
    for block in sorted_blocks:
        upper, lower = float(block["bbox"][1]), float(block["bbox"][3])
        if not bands or upper > ymax + band_gap:
            bands.append([])
            ymax = lower
        bands[-1].append(block)
        ymax = max(ymax, lower)

    ordered = []
    midpoint = page_width / 2
    for band in bands:
        left = [item for item in band
                if (float(item["bbox"][0]) + float(item["bbox"][2])) / 2 < midpoint]
        right = [item for item in band
                 if (float(item["bbox"][0]) + float(item["bbox"][2])) / 2 >= midpoint]
        physically_separate = (
            bool(left) and bool(right)
            and max(float(item["bbox"][2]) for item in left) + column_gap
            <= min(float(item["bbox"][0]) for item in right)
        )
        if physically_separate:
            # Read all of the left column before the right. This prevents
            # mixing the footer recipient list and the signature headings.
            ordered.extend(sorted(left, key=_position))
            ordered.extend(sorted(right, key=_position))
        else:
            # Includes full-width paragraphs and overlapping blocks.
            # Never force a column assignment when boxes actually overlap.
            ordered.extend(sorted(band, key=_position))
    return ordered

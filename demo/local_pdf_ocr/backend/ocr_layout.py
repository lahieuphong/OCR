"""Conservative geometry-only OCR reading-order repair for split footers.

The baseline PaddleOCR detector returns independent quadrilateral lines.
A global (y,x) sort interleaves left-column recipient lists with right-
column signatures. This intentionally narrow algorithm reorders a terminal,
two-column zone only if ALL geometry gates are satisfied.

It NEVER changes text, confidence, polygons, recognition or model weights.
No tokens such as 'Nơi nhận' or 'KT.' are searched: decisions use geometry
only, so spelling mistakes cannot trigger layout changes.
"""
from __future__ import annotations

from collections.abc import Sequence


def _box(line: dict) -> tuple[float, float, float, float]:
    quad = line["polygon"]
    if len(quad) != 4 or any(len(point) != 2 for point in quad):
        raise ValueError("OCR polygon must have four (x,y) corners.")
    xs = [float(p[0]) for p in quad]
    ys = [float(p[1]) for p in quad]
    return min(xs), min(ys), max(xs), max(ys)


def _position(line: dict) -> tuple[float, float, int]:
    x0, y0, _x1, _y1 = _box(line)
    return y0, x0, int(line["line_index"])


def reorder_split_footer(
    lines: Sequence[dict],
    page_width: float,
    page_height: float,
    *,
    spanning_width_ratio: float = 0.65,
    min_column_gap_ratio: float = 0.055,
    footer_start_ratio: float = 0.55,
    max_footer_span_ratio: float = 0.30,
) -> tuple[list[dict], dict]:
    """Return geometry-ordered COPIES and an auditable layout decision.

    The last broad body text line forms a boundary. After that boundary,
    require a lower-page small zone with >=3 left and >=2 right nonspanning
    lines. All left/right bounding boxes must be horizontally disjoint with
    a gutter >=5.5% page width; both columns must overlap vertically.

    Ambiguous layouts remain baseline order; no silent heuristic fallback.
    A line's original detection index is retained in source_line_index.
    """
    if page_width <= 0 or page_height <= 0:
        raise ValueError("Page dimensions must be positive")
    original = sorted((dict(line) for line in lines), key=_position)
    info = {
        "algorithm": "conservative_split_footer_v1",
        "modified": False,
        "original_line_count": len(original),
        "footer_source_line_indices": [],
        "reason": "no_valid_split_footer_geometry",
    }

    anchors = [
        index for index, line in enumerate(original)
        if _box(line)[2] - _box(line)[0] >= spanning_width_ratio * page_width
    ]
    if not anchors:
        return original, info

    anchor = anchors[-1]
    prefix, suffix = original[: anchor + 1], original[anchor + 1:]
    if len(suffix) < 5:
        return original, info

    boxes = [_box(line) for line in suffix]
    min_y = min(box[1] for box in boxes)
    max_y = max(box[3] for box in boxes)
    if (min_y < footer_start_ratio * page_height
            or max_y - min_y > max_footer_span_ratio * page_height):
        return original, info
    if any((box[2] - box[0]) >= spanning_width_ratio * page_width for box in boxes):
        return original, info

    x_sorted = sorted(suffix, key=lambda line: (_box(line)[0], _box(line)[2], _position(line)))
    best = None
    for cut in range(3, len(x_sorted) - 1):
        left, right = x_sorted[:cut], x_sorted[cut:]
        if len(right) < 2:
            continue
        gap = min(_box(line)[0] for line in right) - max(_box(line)[2] for line in left)
        if gap < min_column_gap_ratio * page_width:
            continue
        # Overlapping y ranges are necessary for a true two-column footer.
        left_top, left_end = min(_box(line)[1] for line in left), max(_box(line)[3] for line in left)
        right_top, right_end = min(_box(line)[1] for line in right), max(_box(line)[3] for line in right)
        if min(left_end, right_end) <= max(left_top, right_top):
            continue
        if best is None or gap > best[0]:
            best = (gap, left, right)

    if best is None:
        return original, info

    gap, left, right = best
    ordered = prefix + sorted(left, key=_position) + sorted(right, key=_position)
    for i, line in enumerate(ordered, start=1):
        line["source_line_index"] = line["line_index"]
        line["line_index"] = i
    info.update({
        "modified": True,
        "reason": "disjoint_lower_page_columns",
        "gutter_px": round(gap, 2),
        "anchor_source_line_index": original[anchor]["line_index"],
        "footer_source_line_indices": [line["source_line_index"] for line in ordered[len(prefix):]],
        "left_line_count": len(left),
        "right_line_count": len(right),
    })
    return ordered, info

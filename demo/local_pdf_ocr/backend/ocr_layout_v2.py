"""Conservative, auditable OCR region ordering based only on polygons.

Never changes recognition text, polygon, checkpoint, detector or model
weights. Ambiguous stamp-like fragments are retained in a review zone.
"""
from __future__ import annotations

from statistics import median


def _box(line):
    quad = line["polygon"]
    if len(quad) != 4 or any(len(point) != 2 for point in quad):
        raise ValueError("Expected quadrilateral polygon")
    xs = [float(p[0]) for p in quad]
    ys = [float(p[1]) for p in quad]
    return min(xs), min(ys), max(xs), max(ys)


def _pos(line):
    x0, y0, *_ = _box(line)
    return y0, x0, int(line.get("source_line_index", line["line_index"]))


def analyze_detection_geometry(lines, page_width, page_height, *, page_number=1):
    """Report suspicious detection regions without altering detections."""
    if page_width <= 0 or page_height <= 0:
        raise ValueError("Invalid page size")
    heights = [_box(row)[3] - _box(row)[1] for row in lines]
    med = median(heights) if heights else 0
    flags = []
    for row in lines:
        x0, y0, x1, y1 = _box(row)
        reasons = []
        if (page_number == 1 and y0 < .14 * page_height
                and x0 < .21 * page_width and x1 > .8 * page_width
                and x1 - x0 > .68 * page_width):
            reasons.append("possible_merged_two_column_header")
        if (med and y0 > .12 * page_height
                and y1 - y0 > 1.95 * med and x1 - x0 < .25 * page_width):
            reasons.append("tall_or_skewed_detection_check_stamps")
        if reasons:
            flags.append({
                "source_line_index": int(row.get("source_line_index", row["line_index"])),
                "reasons": reasons,
                "bbox": list(_box(row)),
            })
    return {
        "algorithm": "geometry_only_review_v1",
        "flagged_count": len(flags),
        "flags": flags,
        "model_not_rerun": True,
        "review_required": bool(flags),
    }


def reorder_document_regions(lines, page_width, page_height):
    """Split only an unambiguous two-column zone following a broad body row.

    Left/right bounding boxes must be disjoint, both columns must overlap
    vertically, and at least 4/2 rows must exist. Ambiguous layouts remain
    in the original (y,x) order; no text heuristics or spell corrections.
    """
    if page_width <= 0 or page_height <= 0:
        raise ValueError("Invalid page size")
    original = sorted((dict(row) for row in lines), key=_pos)
    info = {
        "algorithm": "region_columns_v2",
        "modified": False,
        "original_line_count": len(original),
        "reason": "no_unambiguous_region_split",
        "zones": [],
        "review_source_line_indices": [],
        "footer_source_line_indices": [],
    }
    if len(original) < 8:
        return original, info
    wide = [i for i, row in enumerate(original)
            if _box(row)[2] - _box(row)[0] >= .65 * page_width]
    if not wide:
        return original, info

    anchor = wide[-1]
    tail = original[anchor + 1:]
    if len(tail) < 6:
        return original, info
    median_height = median([_box(row)[3] - _box(row)[1] for row in original])
    left_candidates = [row for row in tail
                       if _box(row)[0] < .29 * page_width
                       and _box(row)[2] <= .60 * page_width]
    right_candidates = [row for row in tail
                        if _box(row)[0] >= .53 * page_width
                        and _box(row)[2] >= .76 * page_width]
    if len(left_candidates) < 4 or len(right_candidates) < 2:
        return original, info

    right_first_y = min(_box(row)[1] for row in right_candidates)
    # Keep the closing paragraph above the footer (21-BCT page 2).
    left = [row for row in left_candidates
            if _box(row)[1] >= right_first_y - .6 * median_height]
    right = [row for row in right_candidates
             if _box(row)[1] >= right_first_y - .6 * median_height]
    if len(left) < 4 or len(right) < 2:
        return original, info
    gutter = min(_box(row)[0] for row in right) - max(_box(row)[2] for row in left)
    if gutter < .01 * page_width:
        return original, info
    left_top = min(_box(row)[1] for row in left)
    left_bottom = max(_box(row)[3] for row in left)
    right_top = min(_box(row)[1] for row in right)
    right_bottom = max(_box(row)[3] for row in right)
    if min(left_bottom, right_bottom) <= max(left_top, right_top):
        return original, info

    region_start = min(left_top, right_top)
    prefix = [row for row in original if _box(row)[1] < region_start]
    zone = [row for row in original if _box(row)[1] >= region_start]
    if any(_box(row)[2] - _box(row)[0] >= .65 * page_width for row in zone):
        return original, info

    left_ids, right_ids = {id(row) for row in left}, {id(row) for row in right}
    left_region = [row for row in zone if id(row) in left_ids]
    right_region = [row for row in zone if id(row) in right_ids]
    review_region = [row for row in zone
                     if id(row) not in left_ids and id(row) not in right_ids]
    if len(left_region) < 4 or len(right_region) < 2:
        return original, info
    if len(review_region) > max(3, int(len(zone) * .20)):
        return original, info

    # Require the columns to interleave in the baseline order.
    labels = [("L" if id(row) in left_ids else
               "R" if id(row) in right_ids else "?") for row in zone]
    switches = sum(1 for a, b in zip(labels, labels[1:])
                   if a != b and a != "?" and b != "?")
    if switches < 1:
        return original, info

    for row in prefix:
        row["layout_region"] = "body"
    for row in left_region:
        row["layout_region"] = "left_column"
    for row in right_region:
        row["layout_region"] = "right_column"
    for row in review_region:
        row["layout_region"] = "overprint_review"
        row["review_reasons"] = ["ambiguous_between_columns_check_stamps"]
    ordered = prefix + left_region + right_region + review_region
    if len(ordered) != len(original):
        raise AssertionError("Layout regions lost OCR lines")
    for i, row in enumerate(ordered, 1):
        row["source_line_index"] = int(row.get("source_line_index", row["line_index"]))
        row["line_index"] = i

    info.update({
        "modified": True,
        "reason": "disjoint_columns_after_body",
        "gutter_px": round(gutter, 2),
        "anchor_source_line_index": int(
            original[anchor].get("source_line_index", original[anchor]["line_index"])
        ),
        "footer_source_line_indices": [
            row["source_line_index"]
            for row in left_region + right_region + review_region
        ],
        "review_source_line_indices": [
            row["source_line_index"] for row in review_region
        ],
        "left_line_count": len(left_region),
        "right_line_count": len(right_region),
        "review_line_count": len(review_region),
        "zones": [
            {"name": name, "count": len(group)}
            for name, group in (
                ("body", prefix),
                ("left_column", left_region),
                ("right_column", right_region),
                ("overprint_review", review_region),
            )
        ],
    })
    return ordered, info

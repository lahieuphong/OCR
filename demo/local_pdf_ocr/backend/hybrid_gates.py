"""Frozen H1 v1 trust gates: choose visible PDF text or retain the OCR bytes.

These thresholds are copied unchanged from the reviewed H1 experiment. They
never repair characters, consult reference labels, or tune per document.
"""
from __future__ import annotations

import math
import re
import unicodedata

GATES = {
    # Page classes.
    "native_min_visible_chars": 200,
    "native_min_line_coverage": 0.5,        # share of OCR lines that receive a visible text-layer word
    "hidden_min_share": 0.5,                # invisible or covered characters among all text-layer characters
    # Word -> OCR polygon assignment (PDF points; polygon box = raster pixels / zoom).
    "min_inside_share": 0.5,                # a word centred in the polygon box must lie mostly inside it
    "ambiguous_share": 0.3,                 # a word centred outside but this much inside makes the line ambiguous
    "single_line_spread": 0.6,              # y-centre spread of assigned words, in median word heights
    "duplicate_iou": 0.6,                   # the same word drawn twice at the same place
    "overlap_iou": 0.3,                     # different words drawn over each other
    "space_gap_pt": 0.5,                    # words further apart than this are joined with a space
    # Visibility.
    "cover_share": 0.5,                     # an image/fill drawn later over this share of a word hides it
    # Consistency with the engine's raster.
    "ink_luminance_drop": 40,               # ink = darker than the page's median luminance by this much
    "min_ink_pixels_per_char": 3,           # a visible word leaves ink inside its box
    "word_box_dilation_px": 3,
    "max_unexplained_ink_share": 0.10,      # ink in the polygon box not under any visible text-layer word
    # Consistency with the B1024 reading of the same pixels (guards against misassignment).
    "require_same_token_count": True,
    "max_distance_to_b1024": 0.5,           # Levenshtein / max(len) of the two candidate strings
    # Fonts.
    "trusted_simple_encodings": ("WinAnsiEncoding", "MacRomanEncoding", "StandardEncoding"),
    "legacy_vietnamese_font_pattern": r"^\.?(vn|vps)",  # TCVN3 (.VnTime), VNI-*, VPS: glyphs not what the codes say
    "mupdf_font_name_max_chars": 31,        # MuPDF truncates "ABCDEF+BaseName" to 31 characters in span names
    # Superscripts (MuPDF span flag bit 0): footnote markers have no agreed plain-text form.
    "reject_superscript": True,
}

SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")
LEGACY_FONT = re.compile(GATES["legacy_vietnamese_font_pattern"], re.IGNORECASE)
REJECTED_CATEGORIES = {"Cc", "Cf", "Cn", "Co", "Cs", "Mn", "Mc", "Me"}
COVERING_OBJECTS = ("fill-image", "fill-imgmask", "fill-shade", "fill-path")


def base_font_name(name: str) -> str:
    return SUBSET_PREFIX.sub("", (name or "").lstrip("/"))


def font_trust(fonts: list[dict]) -> dict[str, bool]:
    """Per base font name: trusted only if every font object of that name maps to Unicode reliably.

    Each font: {"basefont", "type", "encoding", "has_tounicode"}. Type3 never; Type0 and
    Identity encodings need a ToUnicode map; simple fonts need ToUnicode or a standard
    encoding without differences; legacy Vietnamese 8-bit fonts never.
    """
    trust: dict[str, bool] = {}
    for font in fonts:
        kind, encoding = font.get("type", ""), font.get("encoding", "") or ""
        name = base_font_name(font.get("basefont", ""))
        if kind == "Type3" or not name or LEGACY_FONT.match(name):
            ok = False
        elif kind == "Type0" or encoding.startswith("Identity"):
            ok = bool(font.get("has_tounicode"))
        else:
            ok = bool(font.get("has_tounicode")) or encoding in GATES["trusted_simple_encodings"]
        # Spans name the font as MuPDF stores it: the subset-prefixed name cut to 31 characters.
        for key in {name, base_font_name((font.get("basefont", "") or "")[:GATES["mupdf_font_name_max_chars"]])}:
            trust[key] = trust.get(key, True) and ok
    return trust


def unicode_problem(text: str, vocabulary: set[str] | None = None) -> str | None:
    """Why a text-layer string cannot be trusted as Unicode, or None."""
    for character in unicodedata.normalize("NFC", text):
        if character == "\ufffd":
            return "replacement_character"
        category = unicodedata.category(character)
        if category in REJECTED_CATEGORIES:
            return "control_or_unassigned_character" if category[0] == "C" else "orphan_combining_mark"
        if category[0] == "L" and not unicodedata.name(character, "").startswith("LATIN"):
            return "non_latin_letter"
        if vocabulary is not None and character not in vocabulary:
            return "out_of_vocabulary_character"
    return None


def box_share_inside(box, region) -> float:
    """Share of ``box`` (x0, y0, x1, y1) lying inside ``region``."""
    inter = max(0.0, min(box[2], region[2]) - max(box[0], region[0])) * max(0.0, min(box[3], region[3]) - max(box[1], region[1]))
    area = max(1e-9, (box[2] - box[0]) * (box[3] - box[1]))
    return inter / area


def iou(a, b) -> float:
    inter = max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def centred_in(word, region) -> bool:
    cx, cy = (word[0] + word[2]) / 2, (word[1] + word[3]) / 2
    return region[0] <= cx <= region[2] and region[1] <= cy <= region[3]


def assign_words(words: list[tuple], region: tuple) -> tuple[list[tuple], str | None]:
    """Words of one polygon box (PDF points) and the geometric problem, if any.

    ``words`` are tuples (x0, y0, x1, y1, text, block, line, word, ...) as PyMuPDF's.
    """
    inside, problem = [], None
    for word in words:
        share = box_share_inside(word[:4], region)
        if centred_in(word, region):
            if share < GATES["min_inside_share"]:
                problem = problem or "word_straddles_polygon"
            inside.append(word)
        elif share >= GATES["ambiguous_share"]:
            problem = problem or "ambiguous_word_assignment"
    if inside and problem is None:
        heights = sorted(w[3] - w[1] for w in inside)
        centres = [(w[1] + w[3]) / 2 for w in inside]
        if max(centres) - min(centres) > GATES["single_line_spread"] * heights[len(heights) // 2]:
            problem = "multi_line_text"
    if inside and problem is None:
        for i, a in enumerate(inside):
            for b in inside[i + 1:]:
                overlap = iou(a[:4], b[:4])
                if a[4] == b[4] and overlap >= GATES["duplicate_iou"]:
                    return inside, "duplicate_text"
                if a[4] != b[4] and overlap >= GATES["overlap_iou"]:
                    problem = problem or "overlapping_text"
    return inside, problem


def assemble(words: list[tuple]) -> tuple[str, bool]:
    """NFC text of one visual line read left to right, and whether that differs from stream order."""
    ordered = sorted(words, key=lambda w: (w[0], w[1]))
    parts = [ordered[0][4]]
    for previous, current in zip(ordered, ordered[1:]):
        parts.append((" " if current[0] - previous[2] > GATES["space_gap_pt"] else "") + current[4])
    stream = sorted(words, key=lambda w: (w[5], w[6], w[7]))
    return unicodedata.normalize("NFC", "".join(parts)), [w[:4] for w in stream] != [w[:4] for w in ordered]


def normalized_distance(a: str, b: str) -> float:
    if not a and not b:
        return 0.0
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1] / max(len(a), len(b))


def covered_words(words: list[tuple], bboxlog: list[tuple]) -> set[int]:
    """Indexes of words over which an image or fill was drawn later (display-list order).

    A word belongs to the earliest text entry whose box contains its centre (the
    conservative choice: a later cover over any candidate entry hides the word).
    """
    hidden = set()
    for index, word in enumerate(words):
        drawn = [i for i, (kind, rect) in enumerate(bboxlog) if kind.endswith("-text") and centred_in(word, rect)]
        if not drawn:
            continue
        for kind, rect in bboxlog[min(drawn) + 1:]:
            if kind in COVERING_OBJECTS and box_share_inside(word[:4], rect) >= GATES["cover_share"]:
                hidden.add(index)
                break
    return hidden


def dark_mask(rgb):
    """Ink pixels of an RGB raster: darker than the page's median luminance by the gate."""
    import numpy as np

    luminance = rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114
    return luminance < float(np.median(luminance)) - GATES["ink_luminance_drop"]


def ink_checks(dark, word_boxes_px: list[tuple], chars: list[int], page_boxes_px: list[tuple], polygon_box_px: tuple):
    """(indexes of words without ink, share of the polygon's ink not under any page word box).

    ``dark`` is a boolean raster (True = ink); boxes are pixel (x0, y0, x1, y1).
    ``page_boxes_px`` are the visible text-layer words of the whole page.
    """
    height, width = dark.shape

    def clip(box, pad=0):
        x0, y0, x1, y1 = box
        return (max(0, int(math.floor(x0)) - pad), max(0, int(math.floor(y0)) - pad),
                min(width, int(math.ceil(x1)) + pad), min(height, int(math.ceil(y1)) + pad))

    blank = []
    for index, (box, count) in enumerate(zip(word_boxes_px, chars)):
        x0, y0, x1, y1 = clip(box)
        if int(dark[y0:y1, x0:x1].sum()) < GATES["min_ink_pixels_per_char"] * max(1, count):
            blank.append(index)
    x0, y0, x1, y1 = clip(polygon_box_px)
    region = dark[y0:y1, x0:x1].copy()
    total = int(region.sum())
    if total == 0:
        return blank, 0.0
    pad = GATES["word_box_dilation_px"]
    for box in page_boxes_px:
        bx0, by0, bx1, by1 = clip(box, pad)
        if bx1 <= x0 or bx0 >= x1 or by1 <= y0 or by0 >= y1:
            continue
        region[max(0, by0 - y0):max(0, by1 - y0), max(0, bx0 - x0):max(0, bx1 - x0)] = False
    return blank, int(region.sum()) / total

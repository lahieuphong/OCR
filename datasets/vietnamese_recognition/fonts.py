"""Fonts for the synthetic lines: found on the system, accepted only if complete.

A font is used only after every character the generator can produce has been
rendered with it and found to be a real glyph. Many fonts that look fine in
Latin text lack part of the Vietnamese range, and a missing glyph would put an
empty box in an image whose label says otherwise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from PIL import ImageFont

FONT_DIRECTORIES = (
    Path("/System/Library/Fonts/Supplemental"),
    Path("/Library/Fonts"),
    Path.home() / "Library" / "Fonts",
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
    Path.home() / ".fonts",
)
SERIF, SANS, MONO = "serif", "sans", "mono"
# Family name as it starts the file name -> (category, weight in the mix).
# Official documents are set in Times New Roman, so Times-like serifs dominate.
FAMILIES = {
    "Times New Roman": (SERIF, 50),
    "Liberation Serif": (SERIF, 50),
    "Tinos": (SERIF, 50),
    "Georgia": (SERIF, 5),
    "DejaVu Serif": (SERIF, 5),
    "Noto Serif": (SERIF, 5),
    "Arial": (SANS, 18),
    "Liberation Sans": (SANS, 18),
    "Arimo": (SANS, 18),
    "Arial Narrow": (SANS, 3),
    "Tahoma": (SANS, 6),
    "Verdana": (SANS, 5),
    "Trebuchet MS": (SANS, 3),
    "DejaVu Sans": (SANS, 5),
    "Noto Sans": (SANS, 5),
    "Courier New": (MONO, 3),
    "Liberation Mono": (MONO, 3),
}
STYLE_WORDS = re.compile(r"[ -]?(Regular|Bold Italic|BoldItalic|Bold|Italic|Oblique)$")
PROBE_SIZE = 40
# No font maps this code point, so it always draws the "missing glyph" shape.
UNMAPPED = "￿"


@dataclass(frozen=True)
class Font:
    path: Path
    family: str
    category: str
    bold: bool
    italic: bool
    weight: int

    @property
    def name(self) -> str:
        style = " ".join(word for word, on in (("Bold", self.bold), ("Italic", self.italic)) if on)
        return f"{self.family} {style}".strip()

    def load(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.path), size, layout_engine=ImageFont.Layout.BASIC)


def describe(path: Path) -> Font | None:
    """The candidate a font file is, judged by its name, or None if it is not one."""
    stem = path.stem
    style = STYLE_WORDS.search(stem)
    family = stem[: style.start()] if style else stem
    family = family.replace("-", " ").strip()
    if family not in FAMILIES:
        return None
    words = style.group(1) if style else ""
    category, weight = FAMILIES[family]
    return Font(path, family, category, "Bold" in words, "Italic" in words or "Oblique" in words, weight)


def glyph(font: ImageFont.FreeTypeFont, character: str) -> tuple[tuple[int, int], bytes]:
    mask = font.getmask(character)
    return mask.size, bytes(mask)


def missing_glyphs(path: Path, characters: str) -> list[str]:
    """Characters of ``characters`` the font cannot draw.

    A character is missing when it renders exactly like a code point the font
    has no glyph for, or renders as nothing at all.
    """
    font = ImageFont.truetype(str(path), PROBE_SIZE, layout_engine=ImageFont.Layout.BASIC)
    placeholder = glyph(font, UNMAPPED)
    missing = []
    for character in characters:
        if character.isspace():
            continue
        shape = glyph(font, character)
        if shape == placeholder or not any(shape[1]):
            missing.append(character)
    return missing


def discover(characters: str, directories: tuple[Path, ...] = FONT_DIRECTORIES) -> tuple[list[Font], dict[str, str]]:
    """Usable fonts, and for each rejected candidate the reason it was rejected."""
    accepted, rejected = [], {}
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.ttf")):
            font = describe(path)
            if font is None:
                continue
            try:
                missing = missing_glyphs(path, characters)
            except OSError as error:
                rejected[path.name] = f"cannot be opened: {error}"
                continue
            if missing:
                rejected[path.name] = f"{len(missing)} glyph(s) missing, e.g. {''.join(missing[:8])}"
            elif not any(font.name == other.name for other in accepted):
                accepted.append(font)
    return accepted, rejected

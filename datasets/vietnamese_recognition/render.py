"""Render a text line and degrade it the way a scanned document looks.

Two images come out of one sample: the clean render, and the augmented one a
recognizer is trained on. Both are fully determined by the sample's seed.

The degradations are deliberately mild and all of a kind a scanner or a
re-compressed PDF produces: slight skew, thicker or thinner strokes, loss of
resolution, blur, bilevel thresholding, uneven ink and paper tone, sensor
noise and JPEG blocks. Nothing bends or stretches the text: warping that never
happens to a flat page would teach the model shapes it will not meet.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageDraw

from fonts import Font

PAPER = 255
# Font size in pixels: (share, smallest, largest). Body text of a page scanned
# at screen resolution is about 30 px tall; stamps and footers are smaller.
SIZE_CLASSES = ((0.15, 12, 17), (0.65, 20, 29), (0.20, 29, 40))
MAX_SKEW_DEGREES = 1.2
MAX_SKEW_PIXELS = 6  # vertical drift from the middle to the end of the line


@dataclass(frozen=True)
class Rendered:
    clean: np.ndarray  # grey, 255 = paper
    augmented: np.ndarray
    font: str
    steps: tuple[str, ...]


def sample_seed(dataset_seed: int, sample_id: str) -> int:
    """A seed that depends only on the dataset seed and the sample, not on order."""
    digest = hashlib.sha256(f"{dataset_seed}:{sample_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def choose_font(fonts: list[Font], text: str, kind: str, rng: random.Random) -> Font:
    """A font for the line: Times-like most of the time, style by kind of line."""
    families = sorted({font.family for font in fonts})
    weights = [next(font.weight for font in fonts if font.family == family) for family in families]
    family = rng.choices(families, weights=weights)[0]
    styles = [font for font in fonts if font.family == family]

    letters = [character for character in text if character.isalpha()]
    heading = bool(letters) and all(character.isupper() for character in letters)
    bold = rng.random() < (0.7 if heading or kind in ("heading", "article") else 0.12)
    italic = rng.random() < (0.55 if kind in ("date_place", "legal_basis") else 0.06)
    exact = [font for font in styles if font.bold == bold and font.italic == italic]
    return rng.choice(exact or [font for font in styles if font.bold == bold] or styles)


def render_clean(text: str, font: Font, rng: random.Random) -> np.ndarray:
    """Black text on white, cropped to the ink with a few pixels of margin."""
    roll = rng.random()
    share = 0.0
    for part, smallest, largest in SIZE_CLASSES:
        share += part
        if roll < share:
            size = rng.randint(smallest, largest)
            break
    face = font.load(size)
    left, top, right, bottom = face.getbbox(text)
    margins = [rng.randint(1, 7), rng.randint(0, 5), rng.randint(1, 7), rng.randint(0, 5)]
    width = (right - left) + margins[0] + margins[2]
    height = (bottom - top) + margins[1] + margins[3]
    image = Image.new("L", (max(width, 4), max(height, 4)), PAPER)
    ImageDraw.Draw(image).text((margins[0] - left, margins[1] - top), text, font=face, fill=0)
    return np.asarray(image)


def skew(image: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    height, width = image.shape
    limit = min(MAX_SKEW_DEGREES, math.degrees(math.atan(MAX_SKEW_PIXELS / max(width / 2, 1))))
    angle = float(rng.uniform(-limit, limit))
    pad = MAX_SKEW_PIXELS + 2
    padded = cv2.copyMakeBorder(image, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=PAPER)
    matrix = cv2.getRotationMatrix2D((padded.shape[1] / 2, padded.shape[0] / 2), angle, 1.0)
    turned = cv2.warpAffine(
        padded, matrix, (padded.shape[1], padded.shape[0]), flags=cv2.INTER_CUBIC, borderValue=PAPER
    )
    # Back to a tight crop, as a detector would cut it.
    ink = np.argwhere(turned < 200)
    if ink.size == 0:
        return image
    (top, left), (bottom, right) = ink.min(axis=0), ink.max(axis=0)
    margin = int(rng.integers(1, 5))
    return turned[max(top - margin, 0) : bottom + margin + 1, max(left - margin, 0) : right + margin + 1]


def augment(
    clean: np.ndarray, rng: np.random.Generator, allow_thinning: bool = True
) -> tuple[np.ndarray, tuple[str, ...]]:
    """A scanned-looking version of ``clean`` and the names of the steps applied.

    Small text tolerates less: the strength of every step that removes detail
    scales with the height of the line, so that the label can still be read
    from the image. An unreadable image with a confident label is worse than
    no sample. For the same reason strokes are only thinned when
    ``allow_thinning`` says the typeface is heavy enough to survive it.
    """
    image, steps = clean, []
    strength = float(np.clip(clean.shape[0] / 32, 0.4, 1.0))

    if clean.shape[0] >= 20 and rng.random() < 0.30:
        # Dark strokes on white: eroding thickens them, dilating thins them.
        thin = allow_thinning and rng.random() < 0.5
        image = (cv2.dilate if thin else cv2.erode)(image, np.ones((2, 2), np.uint8))
        steps.append("stroke")
    if rng.random() < 0.45:
        image = skew(image, rng)
        steps.append("skew")
    if rng.random() < 0.20:
        # A bilevel scan: every pixel is ink or paper, edges are jagged. Applied
        # to the sharp image, where strokes are still solid.
        image = np.where(image < rng.integers(120, 200), 0, PAPER).astype(np.uint8)
        steps.append("bilevel")
        if rng.random() < 0.5:
            image = cv2.GaussianBlur(image, (0, 0), float(rng.uniform(0.3, 0.5)))
    else:
        lowered = rng.random() < 0.40
        if lowered:
            factor = float(rng.uniform(1.0 - 0.42 * strength, 0.92))
            height, width = image.shape
            small = cv2.resize(
                image, (max(int(width * factor), 4), max(int(height * factor), 4)), interpolation=cv2.INTER_AREA
            )
            image = cv2.resize(small, (width, height), interpolation=cv2.INTER_LINEAR)
            steps.append("resolution")
        if rng.random() < (0.30 if lowered else 0.55):
            image = cv2.GaussianBlur(image, (0, 0), float(rng.uniform(0.3, 0.3 + 0.6 * strength)))
            steps.append("blur")

    # Ink is never pure black and paper never pure white.
    ink, paper = float(rng.uniform(0, 75)), float(rng.uniform(212, 255))
    toned = ink + image.astype(np.float32) / PAPER * (paper - ink)
    toned += rng.normal(0.0, float(rng.uniform(1.0, 9.0)), size=image.shape)
    if rng.random() < 0.25:
        # A few specks of dust or toner.
        count = int(rng.integers(1, max(2, image.size // 1500)))
        rows = rng.integers(0, image.shape[0], count)
        columns = rng.integers(0, image.shape[1], count)
        toned[rows, columns] = rng.choice((ink, paper), size=count)
        steps.append("specks")
    image = np.clip(toned, 0, 255).astype(np.uint8)

    if rng.random() < 0.65:
        quality = int(rng.integers(30, 91))
        encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])[1]
        image = cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE)
        steps.append(f"jpeg{quality}")
    return image, tuple(steps)


def render(text: str, kind: str, fonts: list[Font], dataset_seed: int, sample_id: str) -> Rendered:
    """The clean and the augmented image of one sample."""
    seed = sample_seed(dataset_seed, sample_id)
    rng = random.Random(seed)
    font = choose_font(fonts, text, kind, rng)
    clean = render_clean(text, font, rng)
    augmented, steps = augment(clean, np.random.default_rng(seed), allow_thinning=font.bold)
    return Rendered(clean, augmented, font.name, steps)


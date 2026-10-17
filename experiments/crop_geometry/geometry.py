"""Crop geometry for the controlled padding / neighbour-masking experiment.

Only the crop changes. The warp below is the one PaddleX 3.7.2
``CropByPolys(det_box_type="quad")`` performs (minAreaRect on int32 points,
perspective warp, BORDER_REPLICATE, INTER_CUBIC); with zero padding and no mask
it reproduces that operator pixel for pixel (tests/test_geometry.py). The one
deliberate difference: the 90-degree rotation PaddleX applies to tall crops
(height/width >= 1.5) is decided on the UNPADDED polygon, so padding can never
turn a short horizontal word on its side.

Pixel offsets are in the page raster of the local OCR (zoom 2.0, 144 DPI for
every page of the evaluated PDFs); ``pad_for_zoom`` rescales them otherwise.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

STANDARD_ZOOM = 2.0
ROTATE_RATIO = 1.5  # PaddleX get_rotate_crop_image


@dataclass(frozen=True)
class Config:
    name: str
    arm: str  # A baseline, B padding, C padding + mask (D = B at the same padding)
    pad_top: int = 0  # pixels of the zoom-2.0 raster
    pad_bottom: int = 0
    mask_neighbours: bool = False

    def describe(self) -> dict:
        return {"config": self.name, "arm": self.arm, "pad_top_px": self.pad_top, "pad_bottom_px": self.pad_bottom,
                "pad_horizontal_px": 0, "mask_neighbours": self.mask_neighbours}


CONFIGS = (
    Config("A0", "A"),
    # B2/C2 were added after the geometry analysis (synthetic training crops keep ~3 px of margin),
    # before any inference; B4/B8/B12 and C4/C8/C12 are the arms set by the experiment plan.
    Config("B2", "B", 2, 2), Config("B4", "B", 4, 4), Config("B8", "B", 8, 8), Config("B12", "B", 12, 12),
    Config("C2", "C", 2, 2, True), Config("C4", "C", 4, 4, True), Config("C8", "C", 8, 8, True),
    Config("C12", "C", 12, 12, True),
)


def pad_for_zoom(pixels: int, zoom: float) -> int:
    """The same physical offset on a page rendered at another zoom."""
    return int(round(pixels * zoom / STANDARD_ZOOM))


def ordered_quad(polygon) -> np.ndarray:
    """Corners as top-left, top-right, bottom-right, bottom-left (y grows downwards)."""
    points = np.asarray(polygon, dtype=np.float64).reshape(4, 2)
    by_y = points[np.argsort(points[:, 1], kind="stable")]
    top, bottom = by_y[:2], by_y[2:]
    top = top[np.argsort(top[:, 0], kind="stable")]
    bottom = bottom[np.argsort(bottom[:, 0], kind="stable")]
    return np.array([top[0], top[1], bottom[1], bottom[0]])


def expand_vertically(polygon, top: float, bottom: float, width: int, height: int) -> tuple[np.ndarray, bool]:
    """Move the top edge up and the bottom edge down along the line's own vertical
    direction; clip to the page like the OCR engine does. Returns (quad, clipped)."""
    quad = ordered_quad(polygon)
    left, right = quad[3] - quad[0], quad[2] - quad[1]
    down = left / (np.linalg.norm(left) or 1.0) + right / (np.linalg.norm(right) or 1.0)
    down = down / (np.linalg.norm(down) or 1.0)
    out = quad.copy()
    out[[0, 1]] -= top * down
    out[[2, 3]] += bottom * down
    clipped_x, clipped_y = np.clip(out[:, 0], 0, width - 1), np.clip(out[:, 1], 0, height - 1)
    clipped = bool((clipped_x != out[:, 0]).any() or (clipped_y != out[:, 1]).any())
    return np.stack([clipped_x, clipped_y], axis=1), clipped


def minarea_box(points) -> np.ndarray:
    """The ordered rectangle PaddleX derives from a quad (same int32 cast and ordering)."""
    rect = cv2.minAreaRect(np.array(points).astype(np.int32))
    corners = sorted(list(cv2.boxPoints(rect)), key=lambda point: point[0])
    a, d = (0, 1) if corners[1][1] > corners[0][1] else (1, 0)
    b, c = (2, 3) if corners[3][1] > corners[2][1] else (3, 2)
    return np.array([corners[a], corners[b], corners[c], corners[d]])


def crop_size(box: np.ndarray) -> tuple[int, int]:
    """(width, height) of the warped crop, exactly as PaddleX computes them."""
    width = int(max(np.linalg.norm(box[0] - box[1]), np.linalg.norm(box[2] - box[3])))
    height = int(max(np.linalg.norm(box[0] - box[3]), np.linalg.norm(box[1] - box[2])))
    return width, height


def warp(image: np.ndarray, box: np.ndarray) -> np.ndarray:
    """PaddleX get_rotate_crop_image without its rotation step."""
    width, height = crop_size(box)
    target = np.float32([[0, 0], [width, 0], [width, height], [0, height]])
    matrix = cv2.getPerspectiveTransform(box, target)
    return cv2.warpPerspective(image, matrix, (width, height), borderMode=cv2.BORDER_REPLICATE, flags=cv2.INTER_CUBIC)


def rotates(box: np.ndarray) -> bool:
    width, height = crop_size(box)
    return height * 1.0 / width >= ROTATE_RATIO


def background(image: np.ndarray, region: tuple[int, int, int, int], covered: np.ndarray) -> np.ndarray:
    """Paper colour near the line: median of region pixels outside every polygon."""
    x0, y0, x1, y1 = region
    patch = image[y0:y1, x0:x1].reshape(-1, image.shape[2])
    free = patch[~covered[y0:y1, x0:x1].reshape(-1)]
    if len(free) < 20:  # dense layout: fall back to the brightest tenth of the region
        free = patch[patch.sum(axis=1) >= np.percentile(patch.sum(axis=1), 90)]
    return np.median(free, axis=0).astype(image.dtype)


def crop_line(page: np.ndarray, polygon, neighbours: list, config: Config) -> tuple[np.ndarray, dict]:
    """The recognizer input for one line under ``config``, and what was done to get it."""
    height, width = page.shape[:2]
    baseline_box = minarea_box(polygon)
    rotate = rotates(baseline_box)
    info = {"clipped": False, "masked_pixels": 0, "neighbour_pixels_in_band": 0, "rotated": rotate,
            "geometry_applied": False}
    # Baseline arm, and vertical text (its "vertical" padding would run along the text): unchanged crop.
    if (config.pad_top == 0 and config.pad_bottom == 0 and not config.mask_neighbours) or rotate:
        crop = warp(page, baseline_box)
        return (np.rot90(crop) if rotate else crop), info
    info["geometry_applied"] = True
    quad, info["clipped"] = expand_vertically(polygon, config.pad_top, config.pad_bottom, width, height)
    box = minarea_box(quad)
    source = page
    # Neighbour geometry inside the padded region (from detected polygons only, never from text),
    # rasterised on the local window only.
    x0, y0 = (max(0, int(np.floor(box[:, k].min())) - 2) for k in (0, 1))
    x1, y1 = min(width, int(np.ceil(box[:, 0].max())) + 3), min(height, int(np.ceil(box[:, 1].max())) + 3)
    shape, offset = (y1 - y0, x1 - x0), np.array([x0, y0])

    def fill(points) -> np.ndarray:
        mask = np.zeros(shape, np.uint8)
        cv2.fillPoly(mask, [np.round(ordered_quad(points) - offset).astype(np.int32)], 1)
        return mask.astype(bool)

    target, band, others = fill(polygon), fill(quad), np.zeros(shape, bool)
    for other in neighbours:
        corners = ordered_quad(other)
        if corners[:, 0].max() >= x0 and corners[:, 0].min() <= x1 and corners[:, 1].max() >= y0 and corners[:, 1].min() <= y1:
            others |= fill(corners)
    intrusion = band & others & ~target
    info["neighbour_pixels_in_band"] = int(intrusion.sum())
    if config.mask_neighbours and intrusion.any():
        colour = background(page[y0:y1, x0:x1], (0, 0, x1 - x0, y1 - y0), target | others)
        source = page.copy()
        source[y0:y1, x0:x1][intrusion] = colour
        info["masked_pixels"] = int(intrusion.sum())
    return warp(source, box), info  # never rotated: the unpadded line was horizontal

"""Pre-experiment geometry check: choose the padding range from measurements.

Run from repo root:
  .venv-demo\\Scripts\\python.exe -m experiments.crop_geometry.analyze_geometry ^
    --sources <dir>\\experiment_sources.json --training-crops datasets\\vietnamese_recognition\\real_work\\crops ^
    --training-crops datasets\\vietnamese_recognition\\train\\images --output <dir>\\geometry_analysis.json

Reads stored polygons, the page raster the local OCR renders and training crops.
Runs no model and reads no reference text.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from .geometry import CONFIGS, crop_line, ordered_quad

INK_LUMINANCE = 140
TARGET_HEIGHT = 32  # VietOCR B input height


def quantiles(values) -> dict | None:
    values = [v for v in values if v is not None]
    if not values:
        return None
    array = np.asarray(values, dtype=float)
    return {"n": len(values), "min": float(array.min()), "p10": float(np.percentile(array, 10)),
            "median": float(np.median(array)), "p90": float(np.percentile(array, 90)), "max": float(array.max())}


def neighbour_gaps(polygons: list) -> list[tuple[float | None, float | None]]:
    """Per line: gap to the nearest horizontally overlapping polygon above and below (negative = overlap)."""
    boxes = [(q[:, 0].min(), q[:, 1].min(), q[:, 0].max(), q[:, 1].max()) for q in map(ordered_quad, polygons)]
    result = []
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        above, below = None, None
        for j, (a0, b0, a1, b1) in enumerate(boxes):
            if i == j or min(x1, a1) - max(x0, a0) <= 0:
                continue
            centre, other = (y0 + y1) / 2, (b0 + b1) / 2
            if other < centre:
                gap = y0 - b1
                above = gap if above is None else min(above, gap)
            elif other > centre:
                gap = b0 - y1
                below = gap if below is None else min(below, gap)
        result.append((above, below))
    return result


def ink_profile(rgb: np.ndarray) -> dict:
    luminance = rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114
    rows = np.where((luminance < INK_LUMINANCE).sum(axis=1) >= 2)[0]
    height = rgb.shape[0]
    if len(rows) == 0:
        return {"height": height, "ink": False}
    return {"height": height, "ink": True, "top_margin": int(rows[0]), "bottom_margin": int(height - 1 - rows[-1]),
            "touches_top": bool(rows[0] == 0), "touches_bottom": bool(rows[-1] == height - 1)}


def summarize_profiles(profiles: list[dict]) -> dict:
    inked = [p for p in profiles if p["ink"]]
    return {
        "crops": len(profiles), "with_ink": len(inked),
        "touches_top_fraction": round(sum(p["touches_top"] for p in inked) / len(inked), 4) if inked else None,
        "touches_bottom_fraction": round(sum(p["touches_bottom"] for p in inked) / len(inked), 4) if inked else None,
        "height_px": quantiles([p["height"] for p in profiles]),
        "top_margin_fraction_of_height": quantiles([p["top_margin"] / p["height"] for p in inked]),
        "bottom_margin_fraction_of_height": quantiles([p["bottom_margin"] / p["height"] for p in inked]),
    }


def analyze(sources: list[dict], training_dirs: list[Path], sample: int = 600) -> dict:
    import math

    import cv2
    import fitz
    from PIL import Image

    from demo.local_pdf_ocr.backend.engine import iter_images

    heights, gaps_above, gaps_below, edge, zooms, rasters, profiles = [], [], [], [], set(), set(), []
    by_set: dict[str, list[float]] = {}
    for source in sources:
        export = json.loads(Path(source["ocr_json"]).read_text(encoding="utf-8"))
        pages = dict(iter_images(Path(source["pdf"]).read_bytes(), ".pdf"))
        with fitz.open(source["pdf"]) as pdf:  # the engine's zoom rule, per page
            zooms.update(round(min(2.0, math.sqrt(12_000_000 / (pg.rect.width * pg.rect.height))), 4) for pg in pdf)
        for page in export["pages"]:
            image = pages[page["page"]]
            if (image.width, image.height) != (page["width"], page["height"]):
                raise ValueError(f"STOP: raster differs from the export: {source['document']} p{page['page']}")
            rasters.add((image.width, image.height))
            bgr = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
            polygons = [line["polygon"] for line in page["lines"]]
            for polygon, (above, below) in zip(polygons, neighbour_gaps(polygons)):
                quad = ordered_quad(polygon)
                height = float(quad[:, 1].max() - quad[:, 1].min())
                heights.append(height)
                by_set.setdefault(source["set"], []).append(height)
                gaps_above.append(above)
                gaps_below.append(below)
                edge.append(min(quad[:, 1].min(), image.height - 1 - quad[:, 1].max()))
                crop, _ = crop_line(bgr, polygon, [], CONFIGS[0])
                profiles.append(ink_profile(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)))
    training = {}
    for directory in training_dirs:
        # Skip macOS AppleDouble "._*" side files that came along in the training archive.
        files = sorted(f for f in directory.glob("*.png") if not f.name.startswith("._"))[:sample]
        loaded = []
        for path in files:
            with Image.open(path) as image:
                loaded.append(ink_profile(np.asarray(image.convert("RGB"))))
        training[str(directory)] = summarize_profiles(loaded)
    pads = {}
    for pad in (4, 8, 12):
        pads[str(pad)] = {
            "lines_whose_band_reaches_a_neighbour_above": sum(g is not None and g < pad for g in gaps_above),
            "lines_whose_band_reaches_a_neighbour_below": sum(g is not None and g < pad for g in gaps_below),
            "lines_clipped_at_page_edge": sum(e < pad for e in edge),
            "text_scale_vs_baseline": quantiles([h / (h + 2 * pad) for h in heights if h > 0]),
            "resize_scale_to_32px": quantiles([TARGET_HEIGHT / (h + 2 * pad) for h in heights if h > 0]),
        }
    return {
        "schema": "crop_geometry_analysis_v1",
        "lines": len(heights),
        "page_rasters_px": sorted(rasters),
        "page_zooms": sorted(zooms),
        "polygon_height_px": quantiles(heights),
        "polygon_height_px_by_set": {k: quantiles(v) for k, v in by_set.items()},
        "gap_to_neighbour_above_px": quantiles(gaps_above),
        "gap_to_neighbour_below_px": quantiles(gaps_below),
        "lines_without_neighbour_above": sum(g is None for g in gaps_above),
        "overlapping_neighbour_polygons": sum(g is not None and g < 0 for g in gaps_above + gaps_below),
        "baseline_resize_scale_to_32px": quantiles([TARGET_HEIGHT / h for h in heights if h > 0]),
        "baseline_recognizer_crops_ink": summarize_profiles(profiles),
        "training_crops_ink": training,
        "padding": pads,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--training-crops", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise ValueError(f"STOP: will not overwrite {args.output}")
    sources = json.loads(args.sources.read_text(encoding="utf-8"))["sources"]
    report = analyze(sources, args.training_crops)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=lambda o: o.item()), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("lines", "page_rasters_px", "polygon_height_px",
                                              "gap_to_neighbour_above_px", "gap_to_neighbour_below_px")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

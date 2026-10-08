#!/usr/bin/env python3
"""Cut every text line detected by the frozen profile into one image file.

Usage:
    python benchmarks/vietnamese/recognizer_bakeoff/export_line_crops.py

No model runs here. The detection result is read back from the OCR output of
the frozen profile (``experiments/vietnamese_baseline/output/<profile>/``): the
page image OCR ran on, the detected polygons and the text line orientation.
Each polygon becomes one PNG in ``crops/`` and one row of ``manifest.jsonl``.

The crop is produced by the same operator the PP-OCRv6 pipeline applies between
detection and recognition (PaddleX ``CropByPolys``): the minimum-area rectangle
of the polygon is mapped onto an upright rectangle with a perspective
transform, so a slanted line is straightened instead of being cut out with its
axis-aligned bounding box. A line the orientation classifier flagged as upside
down is turned by 180 degrees, as the pipeline does.

Run it once. Every recognizer must read these exact files; they check the
SHA-256 recorded in the manifest before reading a crop.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import bakeoff_common as bakeoff
from common import OUTPUT_ROOT, Profile, finished_documents, page_number, read_json

# What the pipeline calls `text_type: general`: four-point boxes.
DET_BOX_TYPE = "quad"
PAGE_PATTERN = "page_*.json"


def check_frozen_profile(metadata: dict, profile: Profile, document: str) -> None:
    """The OCR output must come from exactly the frozen profile."""
    configuration = metadata["configuration"]
    recorded = (
        metadata["profile"],
        metadata["detection_model"],
        configuration["use_doc_orientation_classify"],
        configuration["use_doc_unwarping"],
        configuration["use_textline_orientation"],
    )
    frozen = (
        profile.name,
        profile.detection_model,
        profile.use_doc_orientation_classify,
        profile.use_doc_unwarping,
        profile.use_textline_orientation,
    )
    if recorded != frozen:
        raise SystemExit(f"{document}: OCR output is {recorded}, the frozen profile is {frozen}.")


def crop_line(image, polygon: list, orientation_angle: int):
    """The image the pipeline hands to the recognition model for one line."""
    # Imported here: PaddleX takes seconds to load and nothing else needs it.
    from paddlex.inference.pipelines.components import CropByPolys, rotate_image

    if orientation_angle not in (-1, 0, 1):
        raise ValueError(f"unexpected text line orientation {orientation_angle}")
    crop = CropByPolys(det_box_type=DET_BOX_TYPE)(image, [polygon])[0]
    # 1 means "upside down"; -1 means the classifier was not used.
    return rotate_image(crop, 180) if orientation_angle == 1 else crop


def page_rows(document: str, page: int, raw: dict) -> list[dict]:
    """Manifest rows of one page, without the crop itself."""
    polygons, texts, scores = raw["rec_polys"], raw["rec_texts"], raw["rec_scores"]
    angles = raw["textline_orientation_angles"]
    if raw["text_type"] != "general":
        raise SystemExit(f"{document} page {page}: text_type is {raw['text_type']!r}.")
    # Recognition keeps every detected line (score threshold 0), so the lists
    # line up one to one. If a line had been dropped, the angles, which are
    # per detected line, could no longer be matched to the recognised lines.
    if raw["dt_polys"] != polygons or not len(polygons) == len(texts) == len(scores) == len(angles):
        raise SystemExit(f"{document} page {page}: detected and recognised lines differ.")
    return [
        {
            "id": bakeoff.crop_id(document, page, index),
            "document": document,
            "page": page,
            # 1-based, like the id; the baseline's lines.jsonl counts from 0.
            "line_index": index,
            "polygon": polygon,
            "paddle_prediction": text,
            "paddle_confidence": float(score),
            "textline_orientation_angle": angle,
        }
        for index, (polygon, text, score, angle) in enumerate(
            zip(polygons, texts, scores, angles), start=1
        )
    ]


def export(profile: Profile, output_root: Path, bakeoff_dir: Path) -> tuple[list[dict], dict]:
    import cv2

    profile_dir = output_root / profile.name
    documents = finished_documents(profile_dir)
    if not documents:
        raise SystemExit(f"No finished documents in {profile_dir}. Run run_benchmark.py first.")

    crops_dir = bakeoff_dir / bakeoff.CROPS_DIR.name
    crops_dir.mkdir(parents=True, exist_ok=True)
    for stale in crops_dir.glob("*.png"):
        stale.unlink()

    rows, sources, detection_parameters = [], {}, []
    for document in documents:
        document_dir = profile_dir / document
        metadata = read_json(document_dir / "metadata.json")
        check_frozen_profile(metadata, profile, document)
        sources[document] = {
            "input_name": Path(metadata["input"]["path"]).name,
            "input_sha256": metadata["input"]["sha256"],
            "ocr_repo_commit": metadata["repo_commit"],
            "pages": metadata["num_pages"],
        }
        for raw_path in sorted((document_dir / "raw").glob(PAGE_PATTERN)):
            raw = read_json(raw_path)
            if raw["text_det_params"] not in detection_parameters:
                detection_parameters.append(raw["text_det_params"])
            # The page as OCR saw it, saved losslessly by run_ocr.py; OpenCV
            # reads it back in the BGR order the pipeline works in.
            image = cv2.imread(str(raw_path.with_suffix(".png")), cv2.IMREAD_COLOR)
            if image is None:
                raise SystemExit(f"Cannot read the page image next to {raw_path}.")
            for row in page_rows(document, page_number(raw_path.stem), raw):
                crop = crop_line(image, row["polygon"], row["textline_orientation_angle"])
                crop_path = crops_dir / f"{row['id']}.png"
                if not cv2.imwrite(str(crop_path), crop):
                    raise SystemExit(f"Cannot write {crop_path}.")
                row["crop_path"] = crop_path.relative_to(bakeoff_dir).as_posix()
                row["crop_width"], row["crop_height"] = int(crop.shape[1]), int(crop.shape[0])
                row["crop_sha256"] = bakeoff.sha256_file(crop_path)
                rows.append(row)

    if len(detection_parameters) != 1:
        raise SystemExit(f"Pages were detected with different parameters: {detection_parameters}")
    from importlib.metadata import version

    metadata = {
        "profile": profile.name,
        "detection_model": profile.detection_model,
        "use_doc_orientation_classify": profile.use_doc_orientation_classify,
        "use_doc_unwarping": profile.use_doc_unwarping,
        "use_textline_orientation": profile.use_textline_orientation,
        "text_det_params": detection_parameters[0],
        "crop_method": f"paddlex CropByPolys(det_box_type={DET_BOX_TYPE!r}) + 180-degree turn "
        "when textline_orientation_angle == 1",
        "paddlex_version": version("paddlex"),
        "opencv_version": cv2.__version__,
        "documents": sources,
        "num_documents": len(sources),
        "num_pages": len({(row["document"], row["page"]) for row in rows}),
        "num_crops": len(rows),
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return rows, metadata


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--bakeoff-dir", type=Path, default=bakeoff.BAKEOFF_DIR)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing export. Predictions made from it become invalid.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest_path = args.bakeoff_dir / bakeoff.MANIFEST.name
    if manifest_path.exists() and not args.force:
        raise SystemExit(
            f"{manifest_path} already exists. The crops are exported once so that every "
            "recognizer reads the same files; pass --force to replace them."
        )

    rows, metadata = export(bakeoff.FROZEN_PROFILE, args.output_root, args.bakeoff_dir)
    bakeoff.write_jsonl(manifest_path, rows)
    bakeoff.write_json(args.bakeoff_dir / bakeoff.EXPORT_METADATA.name, metadata)
    # Read back through the loader, which rejects duplicate ids or crop paths.
    bakeoff.load_manifest(manifest_path)

    print(f"profile:   {metadata['profile']} (detector {metadata['detection_model']})")
    print(f"documents: {metadata['num_documents']}")
    print(f"pages:     {metadata['num_pages']}")
    print(f"crops:     {metadata['num_crops']} -> {args.bakeoff_dir / bakeoff.CROPS_DIR.name}")
    print(f"manifest:  {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

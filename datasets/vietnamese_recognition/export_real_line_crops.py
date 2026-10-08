#!/usr/bin/env python3
"""Detect the text lines of the registered real documents and cut them out.

Usage (PaddlePaddle environment, ``.venv``):
    python datasets/vietnamese_recognition/export_real_line_crops.py

Runs the frozen detection pipeline on every registered document that has not
been processed yet, exactly as the bake-off ran it:

    PP-OCRv6_medium_det
    use_doc_orientation_classify = true
    use_doc_unwarping            = false
    use_textline_orientation     = true

and with the same detection thresholds; a page detected with other parameters
stops the export. Each detected line is cut out with the pipeline's own crop
operator and written once to ``real_work/crops/``. A document that was already
exported is never cut again.

``real_work/manifest.jsonl`` gets one row per crop: ``id``, ``document_id``,
``page``, ``line_index``, ``polygon``, ``crop_path``, ``crop_sha256``,
``width``, ``height``, ``aspect_ratio``. The row also keeps what the pipeline
recognised (``paddle_prediction``). That text is a reference for the annotator
and a means to spot the same document imported twice. It is never a label.

Unless ``--skip-vietocr`` is given, VietOCR then predicts every crop as a second
reference, in its own environment.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import dataset_common as dataset

import bakeoff_common as bakeoff  # noqa: E402  (path set up by dataset_common)
from common import page_number, read_json  # noqa: E402
from export_line_crops import check_frozen_profile, crop_line, page_rows  # noqa: E402

PROFILE = bakeoff.FROZEN_PROFILE
# The detection parameters of the bake-off. The dataset is cut with these or not at all.
FROZEN_DETECTION = {
    "limit_side_len": 64,
    "limit_type": "min",
    "thresh": 0.3,
    "max_side_limit": 4000,
    "box_thresh": 0.6,
    "unclip_ratio": 1.5,
}
# Two documents sharing this share of their recognised lines are one document.
SAME_DOCUMENT_SHARE = 0.5
FINGERPRINT_MIN_CHARACTERS = 20
VIETOCR_PYTHON = dataset.REPO_ROOT / ".venv-vietocr" / "bin" / "python"


def line_fingerprints(texts: list[str]) -> set[str]:
    """Recognised lines long enough to identify a document, lightly normalised."""
    cleaned = (" ".join(dataset.nfc(text).lower().split()) for text in texts)
    return {text for text in cleaned if len(text) >= FINGERPRINT_MIN_CHARACTERS}


def similar_documents(fingerprints: dict[str, set[str]]) -> list[dict]:
    """Pairs of documents that share most of their recognised lines."""
    names = sorted(fingerprints)
    pairs = []
    for index, first in enumerate(names):
        for second in names[index + 1 :]:
            smaller = min(len(fingerprints[first]), len(fingerprints[second]))
            if smaller == 0:
                continue
            share = len(fingerprints[first] & fingerprints[second]) / smaller
            if share >= SAME_DOCUMENT_SHARE:
                pairs.append({"first": first, "second": second, "shared_share": round(share, 3)})
    return pairs


def staged_file(staged_dir: Path, identifier: str) -> Path:
    matches = sorted(staged_dir.glob(f"{identifier}.*"))
    if len(matches) != 1:
        raise SystemExit(f"{identifier}: expected one staged file, found {len(matches)}. Run import_real_documents.py.")
    return matches[0]


def run_detection(source: Path, output_root: Path, device: str) -> None:
    """The frozen pipeline on one document; its output lands in ``<output_root>/<profile>/``."""
    import run_benchmark

    status = run_benchmark.run_ocr.main(run_benchmark.baseline_arguments(PROFILE, source, output_root, device))
    if status != 0:
        raise SystemExit(f"OCR failed on {source}.")


def export_document(identifier: str, document_dir: Path, work_dir: Path) -> list[dict]:
    """Cut every detected line of one document; return its manifest rows."""
    import cv2

    check_frozen_profile(read_json(document_dir / "metadata.json"), PROFILE, identifier)
    crops_dir = work_dir / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for raw_path in sorted((document_dir / "raw").glob("page_*.json")):
        raw = read_json(raw_path)
        if raw["text_det_params"] != FROZEN_DETECTION:
            raise SystemExit(f"{identifier} {raw_path.stem}: detected with {raw['text_det_params']}, not the frozen parameters.")
        image = cv2.imread(str(raw_path.with_suffix(".png")), cv2.IMREAD_COLOR)
        if image is None:
            raise SystemExit(f"Cannot read the page image next to {raw_path}.")
        for row in page_rows(identifier, page_number(raw_path.stem), raw):
            crop = crop_line(image, row["polygon"], row["textline_orientation_angle"])
            path = crops_dir / f"{row['id']}.png"
            if path.exists():
                raise SystemExit(f"{path} already exists: a crop is exported once.")
            if not cv2.imwrite(str(path), crop):
                raise SystemExit(f"Cannot write {path}.")
            height, width = int(crop.shape[0]), int(crop.shape[1])
            row.update(
                document_id=identifier,
                crop_path=path.relative_to(work_dir).as_posix(),
                crop_sha256=dataset.sha256_file(path),
                width=width,
                height=height,
                aspect_ratio=round(width / height, 3),
                # The names the bake-off tools read.
                crop_width=width,
                crop_height=height,
            )
            rows.append(row)
    return rows


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--documents", type=Path, default=dataset.DOCUMENTS)
    parser.add_argument("--work-dir", type=Path, default=dataset.REAL_WORK_DIR)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--skip-vietocr", action="store_true", help="Do not compute the VietOCR reference predictions.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    documents = dataset.read_documents(args.documents)
    if not documents:
        print("No registered document. Put new documents in real_source/ and run import_real_documents.py.")
        return 0
    manifest_path = args.work_dir / "manifest.jsonl"
    manifest = bakeoff.load_manifest(manifest_path) if manifest_path.is_file() else []
    exported = {row["document_id"] for row in manifest}
    ocr_root = args.work_dir / "ocr"

    for document in documents:
        identifier = document["document_id"]
        if identifier in exported:
            continue
        document_dir = ocr_root / PROFILE.name / identifier
        if not (document_dir / "metadata.json").is_file():
            run_detection(staged_file(args.work_dir / "staged", identifier), ocr_root, args.device)
        rows = export_document(identifier, document_dir, args.work_dir)
        manifest.extend(rows)
        bakeoff.write_jsonl(manifest_path, manifest)  # after each document: nothing is cut twice
        print(f"{identifier}: {len(rows)} line crop(s) from {len({row['page'] for row in rows})} page(s)")

    # The same document imported twice (re-scanned, re-saved) shows up as shared text.
    fingerprints: dict[str, set[str]] = {}
    for row in manifest:
        fingerprints.setdefault(row["document_id"], set()).update(line_fingerprints([row["paddle_prediction"]]))
    if bakeoff.MANIFEST.is_file():
        for row in bakeoff.load_manifest():
            name = f"bakeoff:{row['document']}"
            fingerprints.setdefault(name, set()).update(line_fingerprints([row["paddle_prediction"]]))
    pairs = [pair for pair in similar_documents(fingerprints)
             if not (pair["first"].startswith("bakeoff:") and pair["second"].startswith("bakeoff:"))]  # fmt: skip
    bakeoff.write_json(args.work_dir / "document_similarity.json", {"threshold": SAME_DOCUMENT_SHARE, "pairs": pairs})
    for pair in pairs:
        print(f"WARNING: {pair['first']} and {pair['second']} share {pair['shared_share']:.0%} of their lines: "
              "probably the same document")

    counts = {document["document_id"]: 0 for document in documents}
    for row in manifest:
        counts[row["document_id"]] = counts.get(row["document_id"], 0) + 1
    print(f"documents: {len(counts)}, line crops: {len(manifest)} -> {manifest_path}")

    if manifest and not args.skip_vietocr:
        if not VIETOCR_PYTHON.is_file():
            print("VietOCR environment not found: reference predictions skipped (--skip-vietocr silences this).")
        else:
            subprocess.run(
                [str(VIETOCR_PYTHON), str(bakeoff.BAKEOFF_DIR / "run_vietocr.py"), "--manifest", str(manifest_path),
                 "--output", str(args.work_dir / "predictions" / "vietocr.jsonl")],
                check=True,
            )  # fmt: skip
    return 1 if pairs else 0


if __name__ == "__main__":
    sys.exit(main())

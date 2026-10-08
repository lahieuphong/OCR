#!/usr/bin/env python3
"""Lay out the remaining real line crops for human verification as training data.

Usage:
    python datasets/vietnamese_recognition/prepare_real_candidates.py
    python benchmarks/vietnamese/recognizer_bakeoff/annotate.py \\
        --annotation-dir datasets/vietnamese_recognition/real_annotation --target 50

Writes ``real_annotation/manifest.tsv``, an annotation table in the format
``annotate.py`` works on, with ``ground_truth`` empty and ``verified=false`` on
every row. Nothing in it is a label yet: the two predictions are shown to the
annotator and are never used as ground truth. ``build_dataset.py`` takes a row
into training only once a person has verified it.

Left out of the table:

    - every line of the frozen test holdout, by id and by image;
    - "text twins": crops for which a recognizer predicts exactly the text of
      a frozen test line (the same stamp or header on another page). Training
      on them would teach the test set by another route.

All candidates come from the documents the test set was drawn from. Training
on them makes the test set measure those documents rather than new ones; the
audit reports how many such lines are in training.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import dataset_common as dataset

import bakeoff_common as bakeoff  # noqa: E402  (path set up by dataset_common)
from select_annotation_subset import has_annotation_work  # noqa: E402


def candidates(manifest: list[dict], predictions: dict[str, dict], holdout: dataset.Holdout) -> tuple[list[dict], Counter]:
    """Annotation rows for the crops that may become training data, and why others were left out."""
    rows, left_out = [], Counter()
    for crop in manifest:
        texts = {name: predictions[name][crop["id"]]["prediction"] for name in predictions}
        if crop["id"] in holdout.ids or crop["crop_sha256"] in holdout.hashes:
            left_out["frozen test line"] += 1
        elif any(dataset.nfc(text.strip()) in holdout.texts for text in texts.values()):
            left_out["text twin of a frozen test line"] += 1
        else:
            rows.append(
                {
                    "id": crop["id"],
                    "document": crop["document"],
                    "page": crop["page"],
                    "crop_path": crop["crop_path"],
                    "ppocr_prediction": texts[bakeoff.PPOCR],
                    "vietocr_prediction": texts[bakeoff.VIETOCR],
                    "ground_truth": "",
                    "verified": "false",
                    **dict.fromkeys(bakeoff.REVIEW_COLUMNS, ""),
                }
            )
    return rows, left_out


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path, default=dataset.REAL_ANNOTATION_DIR)
    parser.add_argument("--force", action="store_true", help="Replace a table that holds no annotation work yet.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    table = args.output_dir / bakeoff.ANNOTATION_MANIFEST.name
    if table.exists():
        if has_annotation_work(table):
            raise SystemExit(f"{table} already holds annotation work and is never replaced.")
        if not args.force:
            raise SystemExit(f"{table} already exists; pass --force to replace it.")

    holdout = dataset.Holdout.load()
    manifest = bakeoff.load_manifest()
    predictions = {name: bakeoff.load_predictions(path) for name, path in bakeoff.PREDICTION_FILES.items()}
    rows, left_out = candidates(manifest, predictions, holdout)
    bakeoff.write_annotation(table, rows)
    bakeoff.write_json(
        args.output_dir / "candidates_report.json",
        {
            "crops": len(manifest),
            "left_out": dict(left_out),
            "candidates": len(rows),
            "candidates_by_document": dict(Counter(row["document"] for row in rows)),
            "pages_shared_with_the_test_set": len(
                {(row["document"], str(row["page"])) for row in rows}
                & {(row["document"], row["page"]) for row in holdout.rows}
            ),
        },
    )
    print(f"crops: {len(manifest)}")
    for reason, count in left_out.items():
        print(f"left out, {reason}: {count}")
    print(f"candidates awaiting human verification: {len(rows)} -> {table}")
    print("none of them is a training label until a person verifies it with annotate.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())

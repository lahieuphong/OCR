#!/usr/bin/env python3
"""Set aside the unverified lines of the three bake-off documents as legacy candidates.

Usage:
    python datasets/vietnamese_recognition/prepare_legacy_candidates.py

Writes ``legacy_candidates/manifest.tsv``: the crops of the bake-off documents
that are not in the frozen regression set, in the annotation-table format, with
``ground_truth`` empty and ``verified=false``.

These lines are **not training data** and are not to be annotated for now.
They come from the very documents the regression set was drawn from, pages
included; training on them would turn that set into a measure of how well
three documents were memorised. They are kept, marked ``legacy_candidate``, so
that the question can be reopened once an independent blind test is frozen.
No script reads them into a set, and the audit fails if one turns up in a set.

Left out of the table altogether:

    - every line of the frozen regression set, by id and by image;
    - "text twins": crops for which a recognizer predicts exactly the text of
      a frozen line (the same stamp or header on another page).
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import dataset_common as dataset

import bakeoff_common as bakeoff  # noqa: E402  (path set up by dataset_common)
from select_annotation_subset import has_annotation_work  # noqa: E402


ROLE = "legacy_candidate"


def candidates(manifest: list[dict], predictions: dict[str, dict], holdout: dataset.FrozenLines) -> tuple[list[dict], Counter]:
    """Annotation rows for the leftover crops of the bake-off documents, and why others were left out."""
    rows, left_out = [], Counter()
    for crop in manifest:
        texts = {name: predictions[name][crop["id"]]["prediction"] for name in predictions}
        if crop["id"] in holdout.ids or crop["crop_sha256"] in holdout.hashes:
            left_out["frozen regression line"] += 1
        elif any(dataset.nfc(text.strip()) in holdout.texts for text in texts.values()):
            left_out["text twin of a frozen regression line"] += 1
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
    parser.add_argument("--output-dir", type=Path, default=dataset.LEGACY_DIR)
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

    holdout = dataset.FrozenLines.load(dataset.BAKEOFF_REGRESSION)
    manifest = bakeoff.load_manifest()
    predictions = {name: bakeoff.load_predictions(path) for name, path in bakeoff.PREDICTION_FILES.items()}
    rows, left_out = candidates(manifest, predictions, holdout)
    bakeoff.write_annotation(table, rows)
    bakeoff.write_json(
        args.output_dir / "candidates_report.json",
        {
            "role": ROLE,
            "usable_for_training": False,
            "reason": "same documents and pages as the frozen bake-off regression set; "
            "to be reconsidered only after an independent blind test is frozen",
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
    print(f"{ROLE}: {len(rows)} line(s) -> {table}")
    print("not training data, and not to be annotated until an independent blind test is frozen")
    return 0


if __name__ == "__main__":
    sys.exit(main())

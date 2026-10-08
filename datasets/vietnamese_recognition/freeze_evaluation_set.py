#!/usr/bin/env python3
"""Freeze an evaluation set, or check that a frozen one is intact.

Usage:
    python datasets/vietnamese_recognition/freeze_evaluation_set.py --check
    python datasets/vietnamese_recognition/freeze_evaluation_set.py blind_test

There are two frozen sets:

    bakeoff_regression   the 100 lines the recognizer was chosen on. Frozen
                         already; kept for regression and for comparison with
                         the bake-off, not as a final measure of quality.
    blind_test           verified lines of the documents assigned to ``blind``.
                         Freeze it once enough lines are verified, and before
                         any model is selected.

Freezing copies the verified ground truth out of the annotation working table
into ``<set>/<set>.tsv`` and records the SHA-256 of that file next to it. From
then on the set is read-only: this script refuses to write it a second time,
and every reader checks the lock first. No image is copied; each row carries
the id of its line and the SHA-256 of its crop.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import dataset_common as dataset
from dataset_common import BAKEOFF_REGRESSION, BLIND_TEST

import bakeoff_common as bakeoff  # noqa: E402  (path set up by dataset_common)
from evaluate_recognizers import usable_rows  # noqa: E402

FROZEN_SETS = (BAKEOFF_REGRESSION, BLIND_TEST)


def frozen_rows(name: str, annotation: list[dict], crops: dict[str, dict]) -> list[dict]:
    """One frozen row per verified line of ``annotation``, ordered by id."""
    verified, rejected = usable_rows(annotation)
    if rejected:
        raise SystemExit("Cannot freeze: " + "; ".join(rejected[:3]))
    rows = []
    for row in sorted(verified, key=lambda item: item["id"]):
        crop = crops[row["id"]]
        rows.append(
            {
                "id": row["id"],
                "document": row["document"],
                "page": row["page"],
                "line_index": crop["line_index"],
                "ground_truth": dataset.nfc(row["ground_truth"]),
                "crop_sha256": crop["crop_sha256"],
                "split": name,
                "frozen": "true",
                "blind": "true" if name == BLIND_TEST else "false",
            }
        )
    return rows


def freeze_blind_test(args: argparse.Namespace) -> int:
    target = args.directory / BLIND_TEST / f"{BLIND_TEST}.tsv"
    if target.exists():
        raise SystemExit(f"{target} already exists. A frozen set is never written again.")
    documents = {row["document_id"]: row for row in dataset.read_documents(args.documents)}
    table = args.annotation_dir / BLIND_TEST / bakeoff.ANNOTATION_MANIFEST.name
    if not table.is_file() or not args.lines.is_file():
        raise SystemExit("No blind-test annotation to freeze yet.")
    crops = {row["id"]: row for row in bakeoff.load_manifest(args.lines)}
    rows = frozen_rows(BLIND_TEST, bakeoff.read_annotation(table), crops)
    if not rows:
        raise SystemExit("No verified blind-test line to freeze.")
    strangers = sorted({row["document"] for row in rows if documents.get(row["document"], {}).get("split") != "blind"})
    if strangers:
        raise SystemExit(f"Not blind documents: {', '.join(strangers)}. Nothing was frozen.")
    dataset.write_table(target, dataset.FROZEN_COLUMNS, rows)
    digest = dataset.sha256_file(target)
    dataset.write_text_atomic(target.with_suffix(".sha256"), f"{digest}  {target.name}\n")
    print(f"froze {len(rows)} blind-test lines from {len({row['document'] for row in rows})} document(s) -> {target}")
    print(f"lock: {digest}")
    return 0


def check(args: argparse.Namespace) -> int:
    problems = []
    for name in FROZEN_SETS:
        path = args.directory / name / f"{name}.tsv"
        if not path.is_file():
            print(f"{name}: not frozen yet")
            continue
        rows = dataset.load_frozen(name, path)
        print(f"{name}: lock matches, {len(rows)} frozen lines, labels digest {dataset.labels_digest(rows)[:16]}")
        lines = bakeoff.MANIFEST if name == BAKEOFF_REGRESSION else args.lines
        if not lines.is_file():
            print(f"{name}: crop manifest not on this machine, crops not checked")
            continue
        crops = {row["id"]: row for row in bakeoff.load_manifest(lines)}
        found = 0
        for row in rows:
            crop = crops.get(row["id"])
            if crop is None or crop["crop_sha256"] != row["crop_sha256"]:
                problems.append(f"{row['id']}: not the crop recorded in the crop manifest")
                continue
            file = lines.parent / crop["crop_path"]
            if file.is_file():
                if dataset.sha256_file(file) == row["crop_sha256"]:
                    found += 1
                else:
                    problems.append(f"{row['id']}: the crop file has changed")
        print(f"{name}: crops on this machine with the frozen SHA-256: {found}/{len(rows)}")
    for problem in problems:
        print(f"FAIL: {problem}")
    return 1 if problems else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("set", nargs="?", choices=(BLIND_TEST,), help="The set to freeze now.")
    parser.add_argument("--check", action="store_true", help="Verify the frozen sets; write nothing.")
    parser.add_argument("--directory", type=Path, default=dataset.DATASET_DIR)
    parser.add_argument("--documents", type=Path, default=dataset.DOCUMENTS)
    parser.add_argument("--annotation-dir", type=Path, default=dataset.REAL_ANNOTATION_DIR)
    parser.add_argument("--lines", type=Path, default=dataset.REAL_LINES)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.check or args.set is None:
        return check(args)
    return freeze_blind_test(args)


if __name__ == "__main__":
    sys.exit(main())

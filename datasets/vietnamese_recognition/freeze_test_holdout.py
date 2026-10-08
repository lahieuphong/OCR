#!/usr/bin/env python3
"""Freeze the human-verified bake-off lines as the test holdout.

Usage:
    python datasets/vietnamese_recognition/freeze_test_holdout.py            # once
    python datasets/vietnamese_recognition/freeze_test_holdout.py --check    # any time

Freezing copies the verified ground truth out of the annotation working table
into ``test_holdout/test_holdout.tsv`` and records the SHA-256 of that file in
``test_holdout.sha256``. From then on the holdout is read-only: this script
refuses to write it a second time, and every reader checks the lock first.

No image is copied. Each row carries the id of its line and the SHA-256 of its
crop, which ties the ground truth to one exact image file on the machine that
holds the crops.

``--check`` verifies the lock, and, where the crops and the bake-off manifest
are present, that every frozen line still points at its crop.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import dataset_common as dataset

import bakeoff_common as bakeoff  # noqa: E402  (path set up by dataset_common)
from evaluate_recognizers import usable_rows  # noqa: E402


def holdout_rows(annotation: list[dict], crops: dict[str, dict]) -> list[dict]:
    """One frozen row per verified line, ordered by id."""
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
                "split": dataset.TEST,
                "frozen": "true",
            }
        )
    return rows


def freeze(args: argparse.Namespace) -> int:
    if args.holdout.exists():
        raise SystemExit(
            f"{args.holdout} already exists. The holdout is frozen and is never written again."
        )
    crops = {row["id"]: row for row in bakeoff.load_manifest(args.manifest)}
    rows = holdout_rows(bakeoff.read_annotation(args.annotation), crops)
    if not rows:
        raise SystemExit("No verified line to freeze.")
    dataset.write_table(args.holdout, dataset.HOLDOUT_COLUMNS, rows)
    digest = dataset.sha256_file(args.holdout)
    dataset.write_text_atomic(args.lock, f"{digest}  {args.holdout.name}\n")
    characters = sum(len(row["ground_truth"]) for row in rows)
    words = sum(len(row["ground_truth"].split()) for row in rows)
    print(f"froze {len(rows)} lines ({characters} characters, {words} words) -> {args.holdout}")
    print(f"lock: {digest}")
    return 0


def check(args: argparse.Namespace) -> int:
    rows = dataset.load_holdout(args.holdout, args.lock)
    print(f"lock matches: {len(rows)} frozen lines")
    problems = []
    if args.manifest.is_file():
        crops = {row["id"]: row for row in bakeoff.load_manifest(args.manifest)}
        on_disk = 0
        for row in rows:
            crop = crops.get(row["id"])
            if crop is None or crop["crop_sha256"] != row["crop_sha256"]:
                problems.append(f"{row['id']}: not the crop recorded in the bake-off manifest")
                continue
            path = args.manifest.parent / crop["crop_path"]
            if path.is_file():
                on_disk += 1
                if dataset.sha256_file(path) != row["crop_sha256"]:
                    problems.append(f"{row['id']}: the crop file has changed")
        print(f"crops found on this machine with the frozen SHA-256: {on_disk - len(problems)}/{len(rows)}")
    else:
        print("bake-off manifest not present here: crops not checked")
    if args.annotation.is_file():
        working = {row["id"]: row["ground_truth"] for row in bakeoff.read_annotation(args.annotation)}
        moved = [row["id"] for row in rows if working.get(row["id"]) != row["ground_truth"]]
        if moved:
            # Not an error: the frozen file is the reference from now on.
            print(f"note: the annotation working table differs on {len(moved)} line(s); the holdout wins")
    for problem in problems:
        print(f"FAIL: {problem}")
    return 1 if problems else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="Verify the frozen holdout; write nothing.")
    parser.add_argument("--annotation", type=Path, default=bakeoff.ANNOTATION_MANIFEST)
    parser.add_argument("--manifest", type=Path, default=bakeoff.MANIFEST)
    parser.add_argument("--holdout", type=Path, default=dataset.HOLDOUT)
    parser.add_argument("--lock", type=Path, default=dataset.HOLDOUT_LOCK)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return check(args) if args.check else freeze(args)


if __name__ == "__main__":
    sys.exit(main())

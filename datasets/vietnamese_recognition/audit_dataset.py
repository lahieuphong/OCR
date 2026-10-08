#!/usr/bin/env python3
"""Audit the recognition dataset before anything is trained on it.

Usage:
    python datasets/vietnamese_recognition/audit_dataset.py

Reads ``manifests/train.tsv``, ``val.tsv`` and ``test.tsv`` and reports sizes,
duplicates, overlap between splits, Vietnamese letter coverage, the
distribution of line lengths and what the recognizer's resize does to them.

The audit FAILS (exit status 1) when the dataset must not be trained on:

    - a frozen test line is in training or validation, by id or by image;
    - the test manifest is not exactly the frozen holdout;
    - an id occurs twice, or a row sits in the wrong split file;
    - a label is empty, not NFC, longer than the recognizer can decode, or
      holds a character the recognizer has no class for;
    - a real line that no person verified is in training or validation;
    - an image is missing or is not the file the manifest recorded;
    - a Vietnamese letter never occurs in training.

Everything else it finds is reported as a warning for a person to judge.

Outputs: ``manifests/dataset_audit.json``, ``character_coverage.csv`` and
``resize_report.csv``.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import dataset_common as dataset
from dataset_common import LONG_LINE, REAL, SOURCE_TYPES, TEST, TRAIN, VAL

import bakeoff_common as bakeoff  # noqa: E402  (path set up by dataset_common)
from audit_charset import vietnamese_letters  # noqa: E402

# VietOCR's greedy decoder stops after 128 steps, start and end tokens included.
MAX_LABEL_CHARACTERS = 126
RECOGNIZER_HEIGHT = 32
PRETRAINED_MAX_WIDTH = 512
CANDIDATE_MAX_WIDTHS = (512, 768, 1024, 1280)
ASPECT_BUCKETS = (("up to 16:1", 16.0), ("16:1 to 24:1", 24.0), ("24:1 to 32:1", 32.0), ("over 32:1", math.inf))
LENGTH_BUCKETS = (("1-30", 30), ("31-60", 60), ("61-90", 90), ("91+", 10**9))


def bucket(value: float, buckets: tuple[tuple[str, float], ...]) -> str:
    return next(name for name, upper in buckets if value <= upper)


def resized_width(width: int, height: int, max_width: int) -> tuple[int, float]:
    """Width VietOCR gives an image at height 32, and how much it squeezed it.

    Mirrors ``vietocr.tool.translate.resize``: keep the aspect ratio, round the
    width up to a multiple of 10, then clamp it to the allowed range.
    """
    natural = int(RECOGNIZER_HEIGHT * width / height)
    rounded = min(max(math.ceil(natural / 10) * 10, RECOGNIZER_HEIGHT), max_width)
    return rounded, max(natural / max_width, 1.0)


def duplicates(values: list[str]) -> dict[str, int]:
    return {value: count for value, count in Counter(values).items() if count > 1}


def sized(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row["image_width"] and row["image_height"]]


def resize_rows(splits: dict[str, list[dict]]) -> list[dict]:
    """Per split and candidate maximum width: how many lines are squeezed, and how hard."""
    table = []
    for split, rows in splits.items():
        measured = sized(rows)
        for max_width in CANDIDATE_MAX_WIDTHS:
            per_character, squeezed = [], 0
            for row in measured:
                width, squeeze = resized_width(int(row["image_width"]), int(row["image_height"]), max_width)
                per_character.append(width / len(row["text"]))
                squeezed += squeeze > 1.0
            ordered = sorted(per_character)
            table.append(
                {
                    "split": split,
                    "max_width": max_width,
                    "lines": len(measured),
                    "squeezed_lines": squeezed,
                    "squeezed_share": round(squeezed / len(measured), 4) if measured else "",
                    "median_px_per_character": round(statistics.median(ordered), 2) if ordered else "",
                    "p5_px_per_character": round(ordered[int(0.05 * len(ordered))], 2) if ordered else "",
                    "min_px_per_character": round(ordered[0], 2) if ordered else "",
                }
            )
    return table


def audit(root: Path, vocabulary: str, check_images: bool = True) -> dict:
    holdout = dataset.Holdout.load()
    splits = {split: dataset.read_manifest(root / "manifests" / f"{split}.tsv") for split in dataset.SPLITS}
    learning = splits[TRAIN] + splits[VAL]
    failures: list[str] = []
    warnings: list[str] = []

    # --- the frozen test set ---------------------------------------------------
    leaks = holdout.leaks(learning)
    failures += [f"holdout leak: {problem}" for problem in leaks]
    frozen = {row["id"]: (row["ground_truth"], row["crop_sha256"]) for row in holdout.rows}
    tested = {row["id"]: (row["text"], row["crop_sha256"]) for row in splits[TEST]}
    if tested != frozen:
        failures.append("the test manifest is not exactly the frozen holdout")

    # --- identity ----------------------------------------------------------------
    everything = [row for rows in splits.values() for row in rows]
    duplicate_ids = duplicates([row["id"] for row in everything])
    failures += [f"duplicate id: {key}" for key in list(duplicate_ids)[:10]]
    for split, rows in splits.items():
        failures += [f"{row['id']}: split={row['split']} in {split}.tsv" for row in rows if row["split"] != split][:10]
        failures += [f"{row['id']}: unknown source_type {row['source_type']!r}" for row in rows
                     if row["source_type"] not in SOURCE_TYPES][:10]  # fmt: skip
    duplicate_hashes = duplicates([row["crop_sha256"] for row in learning])
    if duplicate_hashes:
        warnings.append(f"{len(duplicate_hashes)} image(s) occur more than once in train/val")

    # --- labels ----------------------------------------------------------------
    allowed = set(vocabulary)
    for row in everything:
        text = row["text"]
        if not text or text != text.strip():
            failures.append(f"{row['id']}: empty label or label with outer whitespace")
        elif not unicodedata.is_normalized("NFC", text):
            failures.append(f"{row['id']}: label is not NFC")
        elif len(text) > MAX_LABEL_CHARACTERS:
            failures.append(f"{row['id']}: label of {len(text)} characters exceeds the decoder limit")
        elif row["split"] != TEST and set(text) - allowed:
            # A test label is what the page says; a training label must be encodable.
            failures.append(f"{row['id']}: characters outside the recognizer vocabulary: {''.join(sorted(set(text) - allowed))}")
    outside_in_test = sorted({character for row in splits[TEST] for character in row["text"]} - allowed)
    if outside_in_test:
        warnings.append(f"test labels use characters the recognizer cannot output: {''.join(outside_in_test)}")
    failures += [
        f"{row['id']}: real line in {row['split']} that no person verified"
        for row in learning
        if row["source_type"] == REAL and row["verified"] != "true"
    ]

    # --- images ----------------------------------------------------------------
    missing_images = 0
    if check_images:
        for row in learning:
            path = root / row["image_path"]
            if not path.is_file() or dataset.sha256_file(path) != row["crop_sha256"]:
                missing_images += 1
                if missing_images <= 5:
                    failures.append(f"{row['id']}: image missing or changed: {row['image_path']}")

    # --- texts across splits ---------------------------------------------------
    texts = {split: [row["text"] for row in rows] for split, rows in splits.items()}
    shared = {
        "train_val": len(set(texts[TRAIN]) & set(texts[VAL])),
        "train_test": len(set(texts[TRAIN]) & set(texts[TEST])),
        "val_test": len(set(texts[VAL]) & set(texts[TEST])),
    }
    if shared["train_val"]:
        warnings.append(f"{shared['train_val']} text(s) occur in both training and validation")
    if shared["train_test"] or shared["val_test"]:
        warnings.append(
            f"{shared['train_test']} training and {shared['val_test']} validation text(s) repeat a frozen test line"
        )
    test_pages = {(row["document"], row["page"]) for row in holdout.rows}
    same_page = [row["id"] for row in learning
                 if row["source_type"] == REAL and (row["source_document"], row["page"]) in test_pages]  # fmt: skip
    if same_page:
        warnings.append(
            f"{len(same_page)} real line(s) in train/val come from a page that also has frozen test lines"
        )

    # --- Vietnamese letters ----------------------------------------------------
    letters = vietnamese_letters()
    counts = {split: Counter(character for text in texts[split] for character in text) for split in splits}
    missing = [letter for letter in letters if counts[TRAIN][letter] == 0]
    failures += [f"Vietnamese letter never seen in training: {letter}" for letter in missing]
    rarest = min(letters, key=lambda letter: counts[TRAIN][letter]) if splits[TRAIN] else ""

    # --- shape of the lines ----------------------------------------------------
    def distribution(rows: list[dict]) -> dict:
        measured = sized(rows)
        return {
            "by_aspect_ratio": dict(
                Counter(bucket(int(row["image_width"]) / int(row["image_height"]), ASPECT_BUCKETS) for row in measured)
            ),
            "by_characters": dict(Counter(bucket(len(row["text"]), LENGTH_BUCKETS) for row in rows)),
            "long_line_subset": sum(row["subset"] == LONG_LINE for row in rows),
            "wider_than_pretrained_limit": sum(
                resized_width(int(row["image_width"]), int(row["image_height"]), PRETRAINED_MAX_WIDTH)[1] > 1.0
                for row in measured
            ),
            "longest_label": max((len(row["text"]) for row in rows), default=0),
        }

    return {
        "result": "FAIL" if failures else "PASS",
        "failures": failures,
        "warnings": warnings,
        "samples": {split: len(rows) for split, rows in splits.items()},
        "source_type": {split: dict(Counter(row["source_type"] for row in rows)) for split, rows in splits.items()},
        "subset": {split: dict(Counter(row["subset"] or "general" for row in rows)) for split, rows in splits.items()},
        "unique_texts": {split: len(set(values)) for split, values in texts.items()},
        "duplicate_texts": {split: len(duplicates(values)) for split, values in texts.items()},
        "texts_shared": shared,
        "duplicate_ids": len(duplicate_ids),
        "duplicate_image_hashes": len(duplicate_hashes),
        "holdout": {
            "lines": len(holdout.rows),
            "train_id_overlap": len({row["id"] for row in splits[TRAIN]} & holdout.ids),
            "val_id_overlap": len({row["id"] for row in splits[VAL]} & holdout.ids),
            "train_hash_overlap": len({row["crop_sha256"] for row in splits[TRAIN]} & holdout.hashes),
            "val_hash_overlap": len({row["crop_sha256"] for row in splits[VAL]} & holdout.hashes),
        },
        "images_checked": check_images,
        "images_missing_or_changed": missing_images,
        "vietnamese_letters": {
            "reference": len(letters),
            "covered_in_train": len(letters) - len(missing),
            "missing_in_train": missing,
            "rarest_in_train": rarest,
            "minimum_occurrences_in_train": counts[TRAIN][rarest] if rarest else 0,
            "covered_in_val": sum(counts[VAL][letter] > 0 for letter in letters),
            "covered_in_test": sum(counts[TEST][letter] > 0 for letter in letters),
        },
        "lines": {split: distribution(rows) for split, rows in splits.items()},
        "resize": resize_rows(splits),
        "letter_counts": {letter: {split: counts[split][letter] for split in splits} for letter in letters},
    }


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=dataset.DATASET_DIR)
    parser.add_argument("--skip-images", action="store_true", help="Do not open and hash the image files.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from build_dataset import recognizer_vocabulary

    args = parse_args(argv)
    report = audit(args.root, recognizer_vocabulary(), check_images=not args.skip_images)
    manifests = args.root / "manifests"
    letter_counts = report.pop("letter_counts")
    bakeoff.write_json(manifests / "dataset_audit.json", report)
    write_csv(
        manifests / "character_coverage.csv",
        ["char", "unicode", *dataset.SPLITS],
        [{"char": letter, "unicode": f"U+{ord(letter):04X}", **counts} for letter, counts in letter_counts.items()],
    )
    write_csv(manifests / "resize_report.csv", list(report["resize"][0]), report["resize"])

    letters, holdout = report["vietnamese_letters"], report["holdout"]
    for split in dataset.SPLITS:
        print(
            f"{split}: {report['samples'][split]} samples {report['source_type'][split]}, "
            f"{report['unique_texts'][split]} unique texts, {report['duplicate_texts'][split]} duplicated"
        )
    print(f"duplicate ids: {report['duplicate_ids']} | duplicate image hashes in train/val: {report['duplicate_image_hashes']}")
    print(
        f"frozen holdout ({holdout['lines']} lines) in train: {holdout['train_id_overlap']} ids, "
        f"{holdout['train_hash_overlap']} images; in val: {holdout['val_id_overlap']} ids, {holdout['val_hash_overlap']} images"
    )
    print(f"texts shared: {report['texts_shared']}")
    print(
        f"Vietnamese letters in train: {letters['covered_in_train']}/{letters['reference']} covered, "
        f"rarest {letters['rarest_in_train']!r} with {letters['minimum_occurrences_in_train']} occurrence(s); "
        f"val covers {letters['covered_in_val']}, test covers {letters['covered_in_test']}"
    )
    for split in dataset.SPLITS:
        lines = report["lines"][split]
        print(
            f"{split} lines: aspect {lines['by_aspect_ratio']} | characters {lines['by_characters']} | "
            f"long-line subset {lines['long_line_subset']} | wider than {PRETRAINED_MAX_WIDTH} px at height "
            f"{RECOGNIZER_HEIGHT}: {lines['wider_than_pretrained_limit']} | longest label {lines['longest_label']}"
        )
    print("resize to height 32: max width -> squeezed lines, median / 5th percentile px per character")
    for row in report["resize"]:
        print(
            f"  {row['split']:5s} {row['max_width']:5d} px: {row['squeezed_lines']:5d}/{row['lines']} squeezed, "
            f"{row['median_px_per_character']} / {row['p5_px_per_character']} px per character"
        )
    for warning in report["warnings"]:
        print(f"warning: {warning}")
    for failure in report["failures"][:25]:
        print(f"FAIL: {failure}")
    print(f"DATA AUDIT: {report['result']}")
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())

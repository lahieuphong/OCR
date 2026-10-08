#!/usr/bin/env python3
"""Audit the recognition dataset, and say whether it is ready to train on.

Usage:
    python datasets/vietnamese_recognition/audit_dataset.py

Reports each of the six sets separately (``real_train``, ``real_val``,
``synthetic_train``, ``synthetic_val``, ``bakeoff_regression``, ``blind_test``):
sizes, duplicates, where the lines come from, Vietnamese letter coverage, the
distribution of text lengths and aspect ratios, and what the recognizer's
resize does to them. Of the blind test only its size is reported: its content
must not steer any decision, so nothing about its lines is shown.

The audit FAILS (exit status 1) on a leak or a broken set:

    - a source document with lines in two sets, a document registered twice,
      one of the bake-off documents registered as new, or two documents in
      different sets that share most of their text;
    - the same image, or the same id, in two sets;
    - a frozen line (bake-off regression, blind test) in another set, or a
      frozen set that no longer matches its frozen file;
    - a real line that no person verified in any set;
    - a legacy candidate line in any set;
    - a label that is empty, not NFC, or that the recognizer cannot encode
      without being marked as such; a missing or changed image;
    - a Vietnamese letter that never occurs in the training lines.

Identical text in two sets is reported as a warning only: administrative
documents repeat the same formulas, and that alone is not a leak.

Separately from PASS or FAIL, the audit states whether the dataset meets the
conditions set for training (``TRAINING READY``).

Outputs: ``manifests/dataset_audit.json``, ``character_coverage.csv`` and
``resize_report.csv``.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import dataset_common as dataset
from dataset_common import (
    BAKEOFF_REGRESSION,
    BLIND_TEST,
    LEARNING_SPLITS,
    LONG_LINE,
    REAL,
    REAL_SPLITS,
    REAL_TRAIN,
    REAL_VAL,
    SOURCE_TYPES,
    SPLITS,
    SYNTHETIC_TRAIN,
    SYNTHETIC_VAL,
    TRAINING_SPLITS,
)

import bakeoff_common as bakeoff  # noqa: E402  (path set up by dataset_common)
from audit_charset import vietnamese_letters  # noqa: E402

# VietOCR's greedy decoder stops after 128 steps, start and end tokens included.
MAX_LABEL_CHARACTERS = 126
RECOGNIZER_HEIGHT = 32
PRETRAINED_MAX_WIDTH = 512
CANDIDATE_MAX_WIDTHS = (512, 768, 1024, 1280)
ASPECT_BUCKETS = (("up to 16:1", 16.0), ("16:1 to 24:1", 24.0), ("24:1 to 32:1", 32.0), ("over 32:1", math.inf))
LENGTH_BUCKETS = (("1-30", 30), ("31-60", 60), ("61-90", 90), ("91+", 10**9))
OUT_OF_VOCABULARY = "out_of_vocabulary"
# Sets whose lines may be described. The blind test is not among them.
OPEN_SPLITS = tuple(split for split in SPLITS if split != BLIND_TEST)

# What must hold before any training run is started.
READINESS = {
    "real_train_verified": 400,
    "real_val_verified": 100,
    "blind_test_verified": 100,
    "train_documents": 6,
    "val_documents": 2,
    "blind_documents": 2,
}


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


def usable(rows: list[dict]) -> list[dict]:
    """Lines a recognizer with the fixed vocabulary can be trained or validated on."""
    return [row for row in rows if row["subset"] != OUT_OF_VOCABULARY]


def resize_rows(splits: dict[str, list[dict]]) -> list[dict]:
    """Per set and candidate maximum width: how many lines are squeezed, and how hard."""
    table = []
    for split in OPEN_SPLITS:
        measured = sized(splits[split])
        for max_width in CANDIDATE_MAX_WIDTHS:
            per_character, squeezed = [], 0
            for row in measured:
                width, squeeze = resized_width(int(row["image_width"]), int(row["image_height"]), max_width)
                per_character.append(width / max(len(row["text"]), 1))  # an empty label is reported, not a crash
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


def describe(rows: list[dict]) -> dict:
    """What may be said about the lines of an open set."""
    measured = sized(rows)
    texts = [row["text"] for row in rows]
    return {
        "samples": len(rows),
        "characters": sum(map(len, texts)),
        "words": sum(len(text.split()) for text in texts),
        "unique_texts": len(set(texts)),
        "duplicate_texts": len(duplicates(texts)),
        "source_type": dict(Counter(row["source_type"] for row in rows)),
        "subset": dict(Counter(row["subset"] or "general" for row in rows)),
        "documents": dict(Counter(row["source_document"] for row in rows if row["source_type"] == REAL)),
        "fonts": dict(Counter(row["font"] for row in rows if row["font"])),
        "by_characters": dict(Counter(bucket(len(text), LENGTH_BUCKETS) for text in texts)),
        "by_aspect_ratio": dict(
            Counter(bucket(int(row["image_width"]) / int(row["image_height"]), ASPECT_BUCKETS) for row in measured)
        ),
        "long_line_subset": sum(row["subset"] == LONG_LINE for row in rows),
        "wider_than_pretrained_limit": sum(
            resized_width(int(row["image_width"]), int(row["image_height"]), PRETRAINED_MAX_WIDTH)[1] > 1.0
            for row in measured
        ),
        "longest_label": max(map(len, texts), default=0),
    }


def annotation_progress(work_dir: Path) -> dict[str, dict]:
    """Lines laid out, verified and set aside in the working table of each real set."""
    progress = {}
    for split in REAL_SPLITS:
        table = work_dir / "annotation" / split / bakeoff.ANNOTATION_MANIFEST.name
        rows = bakeoff.read_annotation(table) if table.is_file() else []
        progress[split] = {
            "selected": len(rows),
            "verified": sum(bakeoff.is_verified(row) for row in rows),
            "skipped": sum(bakeoff.is_excluded(row) for row in rows),
            "pending": sum(bakeoff.is_pending(row) for row in rows),
        }
    return progress


def readiness(splits: dict[str, list[dict]], leak_failures: int) -> dict:
    """The conditions for training, each with what was found."""
    found = {
        "real_train_verified": len(usable(splits[REAL_TRAIN])),
        "real_val_verified": len(usable(splits[REAL_VAL])),
        "blind_test_verified": len(splits[BLIND_TEST]),
        "train_documents": len({row["source_document"] for row in splits[REAL_TRAIN]}),
        "val_documents": len({row["source_document"] for row in splits[REAL_VAL]}),
        "blind_documents": len({row["source_document"] for row in splits[BLIND_TEST]}),
    }
    conditions = {
        name: {"required": required, "found": found[name], "met": found[name] >= required}
        for name, required in READINESS.items()
    }
    conditions["no_document_or_image_leak"] = {"required": 0, "found": leak_failures, "met": leak_failures == 0}
    return {"ready": all(condition["met"] for condition in conditions.values()), "conditions": conditions}


def audit(
    root: Path,
    vocabulary: str,
    documents_path: Path = dataset.DOCUMENTS,
    work_dir: Path = dataset.REAL_WORK_DIR,
    legacy_dir: Path = dataset.LEGACY_DIR,
    check_images: bool = True,
) -> dict:
    regression = dataset.FrozenLines.load(BAKEOFF_REGRESSION)
    splits = dataset.read_splits(root)
    documents = dataset.read_documents(documents_path)
    everything = [row for rows in splits.values() for row in rows]
    failures: list[str] = []
    leaks: list[str] = []  # the subset of failures that are document or image leaks
    warnings: list[str] = []

    # --- frozen sets -----------------------------------------------------------
    others = [row for split, rows in splits.items() if split != BAKEOFF_REGRESSION for row in rows]
    leaks += [f"bake-off regression leak: {problem}" for problem in regression.leaks(others)]
    if {row["id"]: (row["text"], row["crop_sha256"]) for row in splits[BAKEOFF_REGRESSION]} != {
        row["id"]: (row["ground_truth"], row["crop_sha256"]) for row in regression.rows
    }:
        failures.append("the bakeoff_regression manifest is not exactly the frozen set")
    blind_frozen = dataset.frozen_path(BLIND_TEST, root).is_file()
    if blind_frozen:
        blind = dataset.FrozenLines.load(BLIND_TEST, root)
        leaks += [f"blind test leak: {problem}" for problem in blind.leaks([r for r in everything if r["split"] != BLIND_TEST])]
        if {row["id"]: row["text"] for row in splits[BLIND_TEST]} != {row["id"]: row["ground_truth"] for row in blind.rows}:
            failures.append("the blind_test manifest is not exactly the frozen set")

    # --- documents -------------------------------------------------------------
    leaks += dataset.document_leaks(splits)
    registry = {document["document_id"]: document for document in documents}
    benchmark = dataset.benchmark_documents()
    for digest, count in duplicates([document["sha256"] for document in documents]).items():
        leaks.append(f"source document registered {count} times: {digest[:12]}")
    for document in documents:
        if document["sha256"] in benchmark:
            leaks.append(f"{document['document_id']} is the bake-off document {benchmark[document['sha256']]}")
        if document["split"] and document["split"] not in dataset.DOCUMENT_SPLITS:
            failures.append(f"{document['document_id']}: unknown split {document['split']!r}")
        if (document["blind"] == "true") != (document["split"] == "blind"):
            failures.append(f"{document['document_id']}: blind={document['blind']} with split={document['split'] or '-'}")
    for split in REAL_SPLITS:
        for name in sorted({row["source_document"] for row in splits[split]}):
            wanted = dataset.DOCUMENT_SPLITS.get(registry.get(name, {}).get("split", ""))
            if wanted != split:
                leaks.append(f"{name} has lines in {split} but is registered for {wanted or 'no set'}")
    similarity_path = work_dir / "document_similarity.json"
    owner = {name: dataset.DOCUMENT_SPLITS.get(document["split"]) for name, document in registry.items()}
    for pair in json.loads(similarity_path.read_text(encoding="utf-8"))["pairs"] if similarity_path.is_file() else []:
        sets = {BAKEOFF_REGRESSION if name.startswith("bakeoff:") else owner.get(name) for name in (pair["first"], pair["second"])}
        message = f"{pair['first']} and {pair['second']} share {pair['shared_share']:.0%} of their lines"
        if len(sets) > 1:
            leaks.append(f"{message}: probably one document in two sets")
        else:
            warnings.append(f"{message}: probably the same document twice in one set")

    # --- identity --------------------------------------------------------------
    duplicate_ids = duplicates([row["id"] for row in everything])
    failures += [f"duplicate id: {key}" for key in list(duplicate_ids)[:10]]
    image_owner: dict[str, str] = {}
    shared_images = 0
    for row in everything:
        first = image_owner.setdefault(row["crop_sha256"], row["split"])
        if first != row["split"]:
            shared_images += 1
            if shared_images <= 10:
                leaks.append(f"{row['id']}: its image is also in {first}")
    repeated_images = sum(len(duplicates([row["crop_sha256"] for row in rows])) for rows in splits.values())
    if repeated_images:
        warnings.append(f"{repeated_images} image(s) occur more than once within a set")
    for split, rows in splits.items():
        failures += [f"{row['id']}: split={row['split']} in {split}.tsv" for row in rows if row["split"] != split][:10]
        failures += [f"{row['id']}: unknown source_type {row['source_type']!r}" for row in rows
                     if row["source_type"] not in SOURCE_TYPES][:10]  # fmt: skip
        synthetic_set = split in (SYNTHETIC_TRAIN, SYNTHETIC_VAL)
        failures += [f"{row['id']}: a {row['source_type']} line in {split}" for row in rows
                     if (row["source_type"] == REAL) == synthetic_set][:10]  # fmt: skip
        failures += [f"{row['id']}: blind={row['blind']} in {split}" for row in rows
                     if (row["blind"] == "true") != (split == BLIND_TEST)][:10]  # fmt: skip
    failures += [
        f"{row['id']}: real line in {row['split']} that no person verified"
        for row in everything
        if row["source_type"] == REAL and row["verified"] != "true"
    ]

    # --- legacy candidates -----------------------------------------------------
    legacy_table = legacy_dir / bakeoff.ANNOTATION_MANIFEST.name
    legacy = bakeoff.read_annotation(legacy_table) if legacy_table.is_file() else []
    legacy_ids = {row["id"] for row in legacy}
    legacy_in_sets = [row for row in everything if row["split"] != BAKEOFF_REGRESSION and row["id"] in legacy_ids]
    failures += [f"{row['id']}: a legacy candidate line in {row['split']}" for row in legacy_in_sets]

    # --- labels ----------------------------------------------------------------
    allowed = set(vocabulary)
    unencodable = Counter()
    for row in everything:
        text = row["text"]
        outside = set(text) - allowed
        if not text or text != text.strip():
            failures.append(f"{row['id']}: empty label or label with outer whitespace")
        elif not unicodedata.is_normalized("NFC", text):
            failures.append(f"{row['id']}: label is not NFC")
        elif row["split"] in LEARNING_SPLITS and row["subset"] != OUT_OF_VOCABULARY:
            if len(text) > MAX_LABEL_CHARACTERS:
                failures.append(f"{row['id']}: label of {len(text)} characters exceeds the decoder limit")
            if outside:
                failures.append(f"{row['id']}: characters outside the recognizer vocabulary: {''.join(sorted(outside))}")
        if outside:
            unencodable[row["split"]] += 1
    for split, count in unencodable.items():
        if split != BLIND_TEST:
            warnings.append(f"{count} {split} line(s) hold a character the recognizer cannot output")

    # --- images ----------------------------------------------------------------
    missing_images = 0
    if check_images:
        for row in everything:
            if row["split"] == BAKEOFF_REGRESSION:
                continue  # checked against the frozen set by freeze_evaluation_set.py --check
            path = root / row["image_path"]
            if not path.is_file() or dataset.sha256_file(path) != row["crop_sha256"]:
                missing_images += 1
                if missing_images <= 5:
                    failures.append(f"{row['id']}: image missing or changed: {row['image_path']}")

    # --- identical text across sets (a warning: formulas repeat) -----------------
    texts = {split: {row["text"] for row in rows} for split, rows in splits.items()}
    shared_texts = {}
    for index, first in enumerate(SPLITS):
        for second in SPLITS[index + 1 :]:
            count = len(texts[first] & texts[second])
            if count:
                shared_texts[f"{first}/{second}"] = count
    if shared_texts:
        warnings.append(f"identical text in two sets (lines): {shared_texts}")

    # --- Vietnamese letters ------------------------------------------------------
    letters = vietnamese_letters()
    counts = {split: Counter(character for row in splits[split] for character in row["text"]) for split in OPEN_SPLITS}
    training = Counter()
    for split in TRAINING_SPLITS:
        training.update(counts[split])
    missing = [letter for letter in letters if training[letter] == 0]
    failures += [f"Vietnamese letter never seen in training: {letter}" for letter in missing]
    rarest = min(letters, key=lambda letter: training[letter]) if training else ""

    failures = leaks + failures
    gate = readiness(splits, len(leaks))
    gate["ready"] = gate["ready"] and not failures  # a failing dataset is never ready
    return {
        "result": "FAIL" if failures else "PASS",
        "failures": failures,
        "leak_failures": len(leaks),
        "warnings": warnings,
        "samples": {split: len(rows) for split, rows in splits.items()},
        "sets": {split: describe(splits[split]) for split in OPEN_SPLITS},
        "blind_test": {
            "samples": len(splits[BLIND_TEST]),
            "documents": len({row["source_document"] for row in splits[BLIND_TEST]}),
            "frozen": blind_frozen,
            "content": "not reported: the blind test must not steer any decision",
        },
        "documents": {
            "registered": len(documents),
            "by_split": dict(Counter(document["split"] or "unassigned" for document in documents)),
            "with_verified_lines": {split: len({row["source_document"] for row in splits[split]}) for split in REAL_SPLITS},
        },
        "annotation": annotation_progress(work_dir),
        "legacy_candidates": {"lines": len(legacy), "in_any_set": len(legacy_in_sets)},
        "duplicate_ids": len(duplicate_ids),
        "images_in_two_sets": shared_images,
        "images_repeated_within_a_set": repeated_images,
        "texts_shared_between_sets": shared_texts,
        "images_checked": check_images,
        "images_missing_or_changed": missing_images,
        "vietnamese_letters": {
            "reference": len(letters),
            "covered_in_training": len(letters) - len(missing),
            "missing_in_training": missing,
            "rarest_in_training": rarest,
            "minimum_occurrences_in_training": training[rarest] if rarest else 0,
            "covered": {split: sum(counts[split][letter] > 0 for letter in letters) for split in OPEN_SPLITS},
        },
        "resize": resize_rows(splits),
        "readiness": gate,
        "letter_counts": {letter: {split: counts[split][letter] for split in OPEN_SPLITS} for letter in letters},
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
    parser.add_argument("--documents", type=Path, default=dataset.DOCUMENTS)
    parser.add_argument("--work-dir", type=Path, default=dataset.REAL_WORK_DIR)
    parser.add_argument("--legacy-dir", type=Path, default=dataset.LEGACY_DIR)
    parser.add_argument("--skip-images", action="store_true", help="Do not open and hash the image files.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from build_dataset import recognizer_vocabulary
    from evaluate_splits import blind_test_unlocks

    args = parse_args(argv)
    report = audit(args.root, recognizer_vocabulary(), args.documents, args.work_dir, args.legacy_dir, not args.skip_images)
    unlocks = blind_test_unlocks(args.root)
    report["blind_test"]["results_viewed"] = len(unlocks)
    manifests = args.root / "manifests"
    letter_counts = report.pop("letter_counts")
    bakeoff.write_json(manifests / "dataset_audit.json", report)
    write_csv(
        manifests / "character_coverage.csv",
        ["char", "unicode", *OPEN_SPLITS],
        [{"char": letter, "unicode": f"U+{ord(letter):04X}", **counts} for letter, counts in letter_counts.items()],
    )
    write_csv(manifests / "resize_report.csv", list(report["resize"][0]), report["resize"])

    for split in OPEN_SPLITS:
        info = report["sets"][split]
        print(
            f"{split}: {info['samples']} lines, {info['characters']} characters, {info['words']} words, "
            f"{info['unique_texts']} unique texts; source {info['source_type'] or '{}'}"
            + (f"; {len(info['documents'])} document(s)" if info["documents"] else "")
        )
        if info["samples"]:
            print(f"   characters {info['by_characters']} | aspect {info['by_aspect_ratio']} | longest label {info['longest_label']}")
    blind = report["blind_test"]
    print(
        f"blind_test: {blind['samples']} lines from {blind['documents']} document(s); "
        f"frozen: {'yes' if blind['frozen'] else 'no'}; scores viewed: {blind['results_viewed']} time(s); content not reported"
    )
    documents = report["documents"]
    print(f"source documents registered: {documents['registered']} {documents['by_split'] or ''}")
    for split, progress in report["annotation"].items():
        print(f"annotation {split}: {progress['selected']} laid out, {progress['verified']} verified, "
              f"{progress['skipped']} set aside, {progress['pending']} not yet seen")
    print(f"legacy candidates: {report['legacy_candidates']['lines']} line(s), {report['legacy_candidates']['in_any_set']} in a set")
    print(
        f"duplicate ids: {report['duplicate_ids']} | images in two sets: {report['images_in_two_sets']} | "
        f"document and image leaks: {report['leak_failures']}"
    )
    letters = report["vietnamese_letters"]
    print(
        f"Vietnamese letters in training: {letters['covered_in_training']}/{letters['reference']}, rarest "
        f"{letters['rarest_in_training']!r} x{letters['minimum_occurrences_in_training']}; covered per set: {letters['covered']}"
    )
    print("resize to height 32: set, max width -> squeezed lines, median / 5th percentile px per character")
    for row in report["resize"]:
        if row["lines"]:
            print(f"  {row['split']:18s} {row['max_width']:5d} px: {row['squeezed_lines']:5d}/{row['lines']} squeezed, "
                  f"{row['median_px_per_character']} / {row['p5_px_per_character']}")
    for warning in report["warnings"]:
        print(f"warning: {warning}")
    for failure in report["failures"][:25]:
        print(f"FAIL: {failure}")
    print(f"DATA AUDIT: {report['result']}")
    for name, condition in report["readiness"]["conditions"].items():
        mark = "ok " if condition["met"] else "NO "
        print(f"  {mark} {name}: {condition['found']} (required: {condition['required']})")
    print(f"TRAINING READY: {'YES' if report['readiness']['ready'] else 'NO'}")
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())

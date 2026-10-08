#!/usr/bin/env python3
"""Choose which lines of the new real documents a person will verify.

Usage:
    python datasets/vietnamese_recognition/select_real_lines.py

Writes one annotation table per set under ``real_work/annotation/<set>/``, in
the format ``annotate.py`` works on, with ``ground_truth`` empty and
``verified=false`` on every row. A line goes to the set its document was
assigned to (``assign_document_splits.py``); no document is ever split.

    real_train   stratified, so that a few hundred lines still contain every
                 kind of line a recognizer must read: headers, body text,
                 dates, document numbers, agency names, proper names, long and
                 short lines, punctuation, digits, stacked diacritics and
                 poorly scanned lines. 30% of the lines are a uniform random
                 draw, so that ordinary text is represented as it occurs.
    real_val     a uniform random draw from the validation documents.
    blind_test   a uniform random draw from the blind documents. Nothing
                 about a blind line decides whether it is picked.

The strata are judged from the reference predictions and the crop, because
there is no ground truth yet. They steer the sampling and nothing else: no
prediction is ever copied into ``ground_truth``.

More lines are selected than the target of verified lines, since some crops
turn out unreadable. A table that already holds annotation work is never
rewritten; ``--extend`` adds lines to it instead.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import dataset_common as dataset
from dataset_common import BLIND_TEST, REAL_TRAIN, REAL_VAL

import bakeoff_common as bakeoff  # noqa: E402  (path set up by dataset_common)
import select_annotation_subset as stratified  # noqa: E402
from audit_charset import PPOCRV6_DICT, audit  # noqa: E402

SEED = 20261201
# Lines to lay out per set: the target of verified lines plus room for skips.
SELECTION_SIZE = {REAL_TRAIN: 520, REAL_VAL: 140, BLIND_TEST: 140}
VERIFIED_TARGET = {REAL_TRAIN: 400, REAL_VAL: 100, BLIND_TEST: 100}
RANDOM = "random"
# Share of the training selection each stratum contributes, in filling order.
# The uniform random draw comes last and is never below 25%.
TRAIN_SHARES = {
    "header": 0.08,
    "date": 0.05,
    "document_number": 0.06,
    "agency": 0.05,
    "proper_name": 0.05,
    "long_line": 0.07,
    "short_line": 0.05,
    "punctuation": 0.04,
    "digits_symbols": 0.05,
    "complex_diacritics": 0.06,
    "low_quality": 0.04,
    "body": 0.10,
    RANDOM: 0.30,
}
MIN_RANDOM_SHARE = 0.25

DATE = re.compile(r"ngày\s+\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+\d{4}|\b\d{1,2}[/.]\d{1,2}[/.]\d{4}\b", re.IGNORECASE)
DOCUMENT_NUMBER = re.compile(r"\b\d+\s*/\s*(\d{4}\s*/\s*)?[A-ZĐ]{1,8}[a-z]{0,2}\s*-\s*[A-ZĐ0-9]+|\b\d+-[A-ZĐ]{2,3}/TW\b|^Số\s*:?\s*\d")
AGENCY = re.compile(r"\b(Bộ|Sở|Cục|Vụ|Viện|Ban|Ủy ban|Uy ban|Văn phòng|Tổng cục|Chi cục|Hội đồng|Thanh tra|Kho bạc)\s+[A-ZĐ]|"
                    r"\b(BỘ|SỞ|CỤC|ỦY BAN|VĂN PHÒNG|TỔNG CỤC|HỘI ĐỒNG)\s")  # fmt: skip
SHORT_LINE_MAX_CHARACTERS = 20
PUNCTUATION_MIN = 3
LOW_QUALITY_QUANTILE = 0.20


def has_proper_name(text: str) -> bool:
    """Two capitalised words in a row after the first word: a name of a person or place."""
    words = text.split()
    capitalised = [word[:1].isupper() and word[1:].islower() and len(word) > 1 for word in words]
    return any(capitalised[index] and capitalised[index + 1] for index in range(1, len(words) - 1))


def confidence_floor(rows: list[dict]) -> float:
    ordered = sorted(row["confidence"] for row in rows)
    return ordered[max(0, int(len(ordered) * LOW_QUALITY_QUANTILE) - 1)] if ordered else 0.0


def tags_of(row: dict, missing: set[str], small_height: int, low_confidence: float) -> set[str]:
    """Every stratum a line belongs to, judged from its references and its crop."""
    texts = (row["ppocr_prediction"], row["vietocr_prediction"])
    tags = stratified.line_tags(row, *texts, missing, small_height)
    tags.discard("small_text")
    tags.discard("missing_chars")
    if any(DATE.search(text) for text in texts):
        tags.add("date")
    if any(DOCUMENT_NUMBER.search(text) for text in texts):
        tags.add("document_number")
    if any(AGENCY.search(text) for text in texts):
        tags.add("agency")
    if any(has_proper_name(text) for text in texts):
        tags.add("proper_name")
    if 0 < max(map(len, texts)) <= SHORT_LINE_MAX_CHARACTERS:
        tags.add("short_line")
    if max(sum(character in ",;:.()\"'-/" for character in text) for text in texts) >= PUNCTUATION_MIN:
        tags.add("punctuation")
    if row["confidence"] <= low_confidence or row["crop_height"] <= small_height:
        tags.add("low_quality")
    return tags


def quotas_for(split: str, size: int) -> dict[str, int]:
    if split != REAL_TRAIN:
        return {RANDOM: size}
    if TRAIN_SHARES[RANDOM] < MIN_RANDOM_SHARE or abs(sum(TRAIN_SHARES.values()) - 1.0) > 1e-9:
        raise SystemExit("TRAIN_SHARES must sum to 1 and keep at least 25% random lines.")
    quotas = {name: round(share * size) for name, share in TRAIN_SHARES.items() if name != RANDOM}
    quotas[RANDOM] = size - sum(quotas.values())  # whatever rounding left, to the random draw
    return quotas


def pool_rows(lines: list[dict], vietocr: dict[str, dict], documents: set[str]) -> list[dict]:
    """The candidate lines of a set of documents, with their two reference predictions."""
    rows = []
    for line in lines:
        if line["document_id"] not in documents:
            continue
        reference = vietocr.get(line["id"], {})
        confidences = [line["paddle_confidence"]] + ([reference["confidence"]] if reference.get("confidence") is not None else [])
        rows.append(
            {
                "id": line["id"],
                "document": line["document_id"],
                "page": line["page"],
                "line_index": line["line_index"],
                "crop_path": line["crop_path"],
                "crop_height": line["crop_height"],
                "crop_sha256": line["crop_sha256"],
                "ppocr_prediction": line["paddle_prediction"],
                "vietocr_prediction": reference.get("prediction", ""),
                "confidence": min(confidences),
            }
        )
    return rows


def table_rows(chosen: list[dict]) -> list[dict]:
    return [
        {
            "id": row["id"],
            "document": row["document"],
            "page": row["page"],
            "crop_path": row["crop_path"],
            "ppocr_prediction": row["ppocr_prediction"],
            "vietocr_prediction": row["vietocr_prediction"],
            "ground_truth": "",
            "verified": "false",
            **dict.fromkeys(bakeoff.REVIEW_COLUMNS, ""),
        }
        for row in chosen
    ]


def select_for(split: str, pool: list[dict], size: int, seed: int, missing: set[str]) -> tuple[list[dict], dict]:
    """The lines of ``pool`` to annotate for ``split`` and why each was picked."""
    if not pool:
        return [], {}
    small_height = stratified.small_text_height([row["crop_height"] for row in pool])
    low_confidence = confidence_floor(pool)
    # Blind lines are drawn without looking at what they contain.
    tags = {row["id"]: set() if split == BLIND_TEST else tags_of(row, missing, small_height, low_confidence) for row in pool}
    picked = stratified.select(pool, tags, quotas_for(split, min(size, len(pool))), seed)
    chosen = [row for row in pool if row["id"] in picked]
    reasons = {row["id"]: {"selected_by": picked[row["id"]], "tags": sorted(tags[row["id"]])} for row in chosen}
    return chosen, reasons


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--documents", type=Path, default=dataset.DOCUMENTS)
    parser.add_argument("--work-dir", type=Path, default=dataset.REAL_WORK_DIR)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--extend", action="store_true", help="Add lines to tables that already hold annotation work.")
    parser.add_argument("--force", action="store_true", help="Rebuild tables that hold no annotation work yet.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    documents = dataset.read_documents(args.documents)
    lines_path = args.work_dir / "manifest.jsonl"
    if not documents or not lines_path.is_file():
        print("No exported real line yet. Run import_real_documents.py and export_real_line_crops.py first.")
        return 0
    unassigned = [d["document_id"] for d in documents if d["split"] not in dataset.DOCUMENT_SPLITS]
    if unassigned:
        raise SystemExit(f"Not assigned to a split yet: {', '.join(unassigned)}. Run assign_document_splits.py.")

    lines = bakeoff.load_manifest(lines_path)
    vietocr_path = args.work_dir / "predictions" / "vietocr.jsonl"
    vietocr = bakeoff.load_predictions(vietocr_path) if vietocr_path.is_file() else {}
    missing = set(audit(PPOCRV6_DICT)["missing"])

    for name, split in dataset.DOCUMENT_SPLITS.items():
        members = {d["document_id"] for d in documents if d["split"] == name}
        pool = pool_rows(lines, vietocr, members)
        directory = args.work_dir / "annotation" / split
        table = directory / bakeoff.ANNOTATION_MANIFEST.name
        existing = bakeoff.read_annotation(table) if table.is_file() else []
        has_work = any(row["ground_truth"] or bakeoff.is_verified(row) or bakeoff.is_excluded(row) for row in existing)
        reasons_path = directory / bakeoff.SELECTION_REPORT.name

        if existing and has_work:
            if not args.extend:
                print(f"{split}: {len(existing)} lines laid out, annotation in progress (use --extend to add lines)")
                continue
            known = {row["id"] for row in existing}
            fresh = [row for row in pool if row["id"] not in known]
            chosen, reasons = select_for(split, fresh, max(0, SELECTION_SIZE[split] - len(existing)), args.seed, missing)
            old_reasons = json.loads(reasons_path.read_text(encoding="utf-8"))["lines"] if reasons_path.is_file() else {}
            bakeoff.write_annotation(table, existing + table_rows(chosen))
            bakeoff.write_json(reasons_path, {"seed": args.seed, "lines": {**old_reasons, **reasons}})
            print(f"{split}: added {len(chosen)} line(s) to the {len(existing)} already laid out")
            continue
        if existing and not args.force:
            print(f"{split}: {len(existing)} lines already laid out (use --force to select again)")
            continue

        chosen, reasons = select_for(split, pool, SELECTION_SIZE[split], args.seed, missing)
        bakeoff.write_annotation(table, table_rows(chosen))
        bakeoff.write_json(reasons_path, {"seed": args.seed, "pool": len(pool), "lines": reasons})
        by_stratum = Counter(reason["selected_by"] for reason in reasons.values())
        print(
            f"{split}: {len(members)} document(s), {len(pool)} detected line(s), {len(chosen)} laid out "
            f"for a target of {VERIFIED_TARGET[split]} verified; by stratum: {dict(by_stratum)}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

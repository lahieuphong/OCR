#!/usr/bin/env python3
"""Pick the line crops a person will transcribe, and lay out the annotation table.

Usage:
    python benchmarks/vietnamese/recognizer_bakeoff/select_annotation_subset.py

Writes ``annotation/manifest.tsv`` with ``ground_truth`` empty and
``verified=false`` on every row, copies the selected crops to
``annotation/candidates/`` and records why each line was picked in
``annotation/selection.json``. No prediction is ever copied into
``ground_truth``.

The sample is stratified so that a small set still covers the cases that
matter. Strata are filled in the order below, each up to its quota, spreading
the picks over documents and pages; the last stratum is a uniform random draw
from everything not picked yet, so the set is not only hand-chosen categories.

The strata are computed from the two predictions and the crop size, since
there is no ground truth yet. They only steer the sampling: a line tagged
``header`` because its prediction is in capitals may turn out to be something
else once a person reads it.
"""

from __future__ import annotations

import argparse
import random
import shutil
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import bakeoff_common as bakeoff
from audit_charset import PPOCRV6_DICT, audit

DEFAULT_SEED = 20261008
# Stratum -> number of lines it contributes, in filling order (150 in total).
QUOTAS = {
    "header": 20,
    "small_text": 12,
    "digits_symbols": 20,
    "long_line": 20,
    "complex_diacritics": 20,
    "missing_chars": 24,
    "body": 10,
    "random": 24,
}
RANDOM = "random"

HEADER_MIN_LETTERS = 4
HEADER_UPPERCASE_RATIO = 0.7
DIGITS_SYMBOLS_MIN = 4
LONG_LINE_MIN_CHARACTERS = 60
COMPLEX_DIACRITICS_MIN = 3
# Crops no taller than this share of all crops count as small text.
SMALL_TEXT_QUANTILE = 0.10


def uppercase_ratio(text: str) -> tuple[float, int]:
    letters = [character for character in text if character.isalpha()]
    if not letters:
        return 0.0, 0
    return sum(character.isupper() for character in letters) / len(letters), len(letters)


def digits_and_symbols(text: str) -> int:
    """Digits plus symbols, not counting the punctuation of ordinary prose."""
    return sum(
        character.isdigit()
        or unicodedata.category(character)[0] == "S"
        or character in "/\\@%&#()[]{}-_:"
        for character in text
    )


def double_marked_letters(text: str) -> int:
    """Letters carrying two diacritics, such as ``ệ`` (circumflex and dot below)."""
    return sum(
        sum(unicodedata.category(mark) == "Mn" for mark in unicodedata.normalize("NFD", character))
        >= 2
        for character in text
    )


def small_text_height(heights: list[int]) -> int:
    ordered = sorted(heights)
    return ordered[max(0, int(len(ordered) * SMALL_TEXT_QUANTILE) - 1)]


def line_tags(
    row: dict, ppocr_text: str, vietocr_text: str, missing: set[str], small_height: int
) -> set[str]:
    """Every stratum a line belongs to, judged from predictions and crop size."""
    texts = (ppocr_text, vietocr_text)
    tags = set()
    if any(
        ratio >= HEADER_UPPERCASE_RATIO and letters >= HEADER_MIN_LETTERS
        for ratio, letters in map(uppercase_ratio, texts)
    ):
        tags.add("header")
    if row["crop_height"] <= small_height:
        tags.add("small_text")
    if max(map(digits_and_symbols, texts)) >= DIGITS_SYMBOLS_MIN:
        tags.add("digits_symbols")
    if max(map(len, texts)) >= LONG_LINE_MIN_CHARACTERS:
        tags.add("long_line")
    if max(map(double_marked_letters, texts)) >= COMPLEX_DIACRITICS_MIN:
        tags.add("complex_diacritics")
    # PP-OCRv6 cannot output these letters; VietOCR can, so its prediction is
    # the only hint that the line contains one.
    if any(character in missing for text in texts for character in text):
        tags.add("missing_chars")
    if not tags & {"header", "small_text"}:
        tags.add("body")
    return tags


def spread_order(rows: list[dict], rng: random.Random) -> list[dict]:
    """``rows`` reordered to alternate between documents, then between pages."""
    by_document: dict[str, dict[int, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        by_document[row["document"]][row["page"]].append(row)

    def interleave(queues: list[list[dict]]) -> list[dict]:
        merged = []
        while any(queues):
            for queue in queues:
                if queue:
                    merged.append(queue.pop(0))
        return merged

    per_document = []
    for document in sorted(by_document):
        pages = []
        for page in sorted(by_document[document]):
            lines = by_document[document][page]
            rng.shuffle(lines)
            pages.append(lines)
        per_document.append(interleave(pages))
    return interleave(per_document)


def select(rows: list[dict], tags: dict[str, set[str]], quotas: dict[str, int], seed: int) -> dict[str, str]:
    """Selected id -> the stratum that picked it."""
    rng = random.Random(seed)
    selected: dict[str, str] = {}
    for stratum, quota in quotas.items():
        available = [row for row in rows if row["id"] not in selected]
        if stratum == RANDOM:
            picks = rng.sample(available, min(quota, len(available)))
        else:
            tagged = [row for row in available if stratum in tags[row["id"]]]
            picks = spread_order(tagged, rng)[:quota]
        for row in picks:
            selected[row["id"]] = stratum
    return selected


def has_annotation_work(path: Path) -> bool:
    return any(
        row["ground_truth"] or bakeoff.is_verified(row) for row in bakeoff.read_annotation(path)
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=bakeoff.MANIFEST)
    parser.add_argument("--annotation-dir", type=Path, default=bakeoff.ANNOTATION_DIR)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--force", action="store_true", help="Replace an annotation table that has no ground truth yet."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    table_path = args.annotation_dir / bakeoff.ANNOTATION_MANIFEST.name
    if table_path.exists():
        if has_annotation_work(table_path):
            raise SystemExit(
                f"{table_path} already holds ground truth. It is never replaced: "
                "move it away yourself if you really want a new selection."
            )
        if not args.force:
            raise SystemExit(f"{table_path} already exists; pass --force to replace it.")

    manifest = bakeoff.load_manifest(args.manifest)
    base_dir = args.manifest.parent
    predictions = {
        name: bakeoff.load_predictions(path) for name, path in bakeoff.PREDICTION_FILES.items()
    }
    bakeoff.check_same_ids(
        {"manifest": {row["id"] for row in manifest}}
        | {name: set(rows) for name, rows in predictions.items()}
    )

    missing = set(audit(PPOCRV6_DICT)["missing"])
    small_height = small_text_height([row["crop_height"] for row in manifest])
    tags = {
        row["id"]: line_tags(
            row,
            predictions[bakeoff.PPOCR][row["id"]]["prediction"],
            predictions[bakeoff.VIETOCR][row["id"]]["prediction"],
            missing,
            small_height,
        )
        for row in manifest
    }
    selected = select(manifest, tags, QUOTAS, args.seed)

    candidates_dir = args.annotation_dir / bakeoff.CANDIDATES_DIR.name
    candidates_dir.mkdir(parents=True, exist_ok=True)
    for stale in candidates_dir.glob("*.png"):
        stale.unlink()

    table = []
    for row in manifest:  # reading order, so neighbouring lines stay together
        if row["id"] not in selected:
            continue
        candidate = candidates_dir / f"{row['id']}.png"
        shutil.copyfile(bakeoff.verified_crop_path(row, base_dir), candidate)
        table.append(
            {
                "id": row["id"],
                "document": row["document"],
                "page": row["page"],
                "crop_path": candidate.relative_to(base_dir).as_posix(),
                "ppocr_prediction": predictions[bakeoff.PPOCR][row["id"]]["prediction"],
                "vietocr_prediction": predictions[bakeoff.VIETOCR][row["id"]]["prediction"],
                "ground_truth": "",
                "verified": "false",
            }
        )
    bakeoff.write_annotation(table_path, table)

    by_stratum = Counter(selected.values())
    by_document = Counter(row["document"] for row in table)
    by_page = Counter(f"{row['document']} p{row['page']}" for row in table)
    bakeoff.write_json(
        args.annotation_dir / bakeoff.SELECTION_REPORT.name,
        {
            "seed": args.seed,
            "pool": len(manifest),
            "selected": len(table),
            "quotas": QUOTAS,
            "selected_by_stratum": dict(by_stratum),
            "selected_by_document": dict(by_document),
            "selected_by_page": dict(by_page),
            "small_text_max_height_px": small_height,
            "lines_tagged_in_pool": dict(Counter(tag for line in tags.values() for tag in line)),
            "lines": {
                row["id"]: {"selected_by": selected[row["id"]], "tags": sorted(tags[row["id"]])}
                for row in table
            },
        },
    )

    print(f"selected {len(table)} of {len(manifest)} lines (seed {args.seed})")
    print("by stratum:  " + ", ".join(f"{name} {by_stratum[name]}" for name in QUOTAS))
    print("by document: " + ", ".join(f"{name} {count}" for name, count in sorted(by_document.items())))
    print(f"pages covered: {len(by_page)}")
    print(f"wrote {table_path} (ground_truth empty, verified=false)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

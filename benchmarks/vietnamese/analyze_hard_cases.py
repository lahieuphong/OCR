#!/usr/bin/env python3
"""Count how often each hard case is recognised correctly by each profile.

Usage:
    python benchmarks/vietnamese/analyze_hard_cases.py

For every entry of ``hard_cases.txt`` this finds its occurrences in the
human-verified ground truth, then looks at what each profile recognised at that
position. Writes ``results/hard_cases.csv``.

This is analysis only. The list is never used to change a prediction.
"""

from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path

from common import (
    GROUND_TRUTH_DIR,
    HARD_CASES_FILE,
    OUTPUT_ROOT,
    PROFILE_A,
    PROFILE_B,
    RESULTS_DIR,
    load_verified_ground_truth,
)
from evaluate import PENDING_MESSAGE, align, load_predictions, nfc, write_csv

COLUMNS = (
    "word",
    "occurrences_in_gt",
    "correct_A",
    "wrong_A",
    "correct_B",
    "wrong_B",
    "example_errors",
)
MAX_EXAMPLES = 3
MISSING = "∅"


def load_hard_cases(path: Path) -> list[str]:
    with path.open(encoding="utf-8-sig") as stream:
        return [nfc(line.strip()) for line in stream if line.strip()]


def token_core(token: str) -> str:
    """The token without the punctuation attached to its ends."""

    def is_word_character(character: str) -> bool:
        return unicodedata.category(character)[0] in "LMN"

    start, end = 0, len(token)
    while start < end and not is_word_character(token[start]):
        start += 1
    while end > start and not is_word_character(token[end - 1]):
        end -= 1
    return token[start:end]


def judge_page(reference: str, hypothesis: str, cases: list[str]) -> dict[str, list]:
    """For each case, one entry per occurrence in the reference.

    An entry is ``None`` when the profile recognised the occurrence exactly
    (same letters, accents and case), otherwise the ``truth -> prediction``
    pair. Matching the list against the reference ignores case, so ``nguyễn``
    also finds ``Nguyễn``.
    """
    reference_tokens = [nfc(token) for token in reference.split()]
    hypothesis_tokens = [nfc(token) for token in hypothesis.split()]
    reference_cores = [token_core(token) for token in reference_tokens]
    hypothesis_cores = [token_core(token) for token in hypothesis_tokens]
    aligned = {
        i: j
        for operation, i, j in align(reference_tokens, hypothesis_tokens)
        if operation in ("equal", "substitute")
    }
    folded = [core.casefold() for core in reference_cores]

    verdicts: dict[str, list] = {}
    for case in cases:
        words = case.casefold().split()
        verdicts[case] = []
        for start in range(len(folded) - len(words) + 1):
            if folded[start : start + len(words)] != words:
                continue
            positions = range(start, start + len(words))
            truth = [reference_cores[i] for i in positions]
            predicted = [
                hypothesis_cores[aligned[i]] if i in aligned else MISSING for i in positions
            ]
            verdicts[case].append(
                None if predicted == truth else f"{' '.join(truth)} -> {' '.join(predicted)}"
            )
    return verdicts


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile-a", default=PROFILE_A.name)
    parser.add_argument("--profile-b", default=PROFILE_B.name)
    parser.add_argument("--hard-cases", type=Path, default=HARD_CASES_FILE)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--ground-truth-dir", type=Path, default=GROUND_TRUTH_DIR)
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    ground_truth, skipped = load_verified_ground_truth(args.ground_truth_dir)
    for reason in skipped:
        print(f"skipped {reason}")
    if not ground_truth:
        print(f"HARD CASES: {PENDING_MESSAGE.split(': ', 1)[1]}")
        return 0

    cases = load_hard_cases(args.hard_cases)
    pages = sorted(ground_truth)
    labels = {"A": args.profile_a, "B": args.profile_b}
    verdicts = {label: {case: [] for case in cases} for label in labels}
    for label, profile in labels.items():
        predictions = load_predictions(args.output_root, profile, pages)
        for key in pages:
            for case, entries in judge_page(ground_truth[key], predictions[key], cases).items():
                verdicts[label][case].extend(entries)

    rows = []
    for case in cases:
        examples = []
        for label in labels:
            wrong = [entry for entry in verdicts[label][case] if entry is not None]
            for example in list(dict.fromkeys(wrong))[:MAX_EXAMPLES]:
                examples.append(f"{label}: {example}")
        row = {"word": case, "occurrences_in_gt": len(verdicts["A"][case])}
        for label in labels:
            entries = verdicts[label][case]
            row[f"correct_{label}"] = sum(entry is None for entry in entries)
            row[f"wrong_{label}"] = sum(entry is not None for entry in entries)
        row["example_errors"] = " | ".join(examples)
        rows.append(row)

    write_csv(args.results_dir / "hard_cases.csv", COLUMNS, rows)
    print(f"verified pages analysed: {len(pages)}  (A = {args.profile_a}, B = {args.profile_b})")
    for row in rows:
        print(
            f"{row['word']}: {row['occurrences_in_gt']} in GT | "
            f"A {row['correct_A']} ok / {row['wrong_A']} wrong | "
            f"B {row['correct_B']} ok / {row['wrong_B']} wrong"
            + (f" | {row['example_errors']}" if row["example_errors"] else "")
        )
    print(f"wrote {args.results_dir / 'hard_cases.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

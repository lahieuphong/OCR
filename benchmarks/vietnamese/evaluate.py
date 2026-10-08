#!/usr/bin/env python3
"""CER / WER of each profile against human-verified ground truth.

Usage:
    python benchmarks/vietnamese/evaluate.py

Only pages recorded as verified (see ``prepare_ground_truth.py verify``) are
scored. Without any, nothing is computed and the script reports
``CER/WER: PENDING HUMAN-VERIFIED GROUND TRUTH``.

Four rates are reported per page, all as ``edit distance / reference length``:

    cer_raw  characters, text compared exactly as it is
    cer_nfc  characters, both sides normalised to Unicode NFC first
    wer_raw  whitespace-separated tokens, compared exactly as they are
    wer_nfc  whitespace-separated tokens, both sides NFC first

Nothing else is normalised: no lowercasing, no accent stripping, no punctuation
handling, no correction. Corpus totals are micro-averages, i.e. the summed edit
distance over the summed reference length, so long pages weigh more than short
ones.

Outputs, in ``results/``: ``metrics.csv`` (per page), ``metrics_summary.csv``
(per profile) and ``errors.jsonl`` (one record per word-level error).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import unicodedata
from pathlib import Path
from typing import Sequence

from common import (
    GROUND_TRUTH_DIR,
    OUTPUT_ROOT,
    PROFILES,
    RESULTS_DIR,
    lines_to_text,
    load_page_lines,
    load_verified_ground_truth,
    write_text,
)

PENDING_MESSAGE = "CER/WER: PENDING HUMAN-VERIFIED GROUND TRUTH"
CONTEXT_WORDS = 5

PAGE_COLUMNS = (
    "profile",
    "document",
    "page",
    "characters_gt",
    "words_gt",
    "cer_raw",
    "cer_nfc",
    "wer_raw",
    "wer_nfc",
    "char_errors_raw",
    "char_errors_nfc",
    "characters_gt_nfc",
    "word_errors_raw",
    "word_errors_nfc",
)
SUMMARY_COLUMNS = (
    "profile",
    "pages",
    "characters_gt",
    "words_gt",
    "micro_cer_raw",
    "micro_cer_nfc",
    "micro_wer_raw",
    "micro_wer_nfc",
)


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def strip_marks(text: str) -> str:
    """Remove combining marks (tone marks, breve, circumflex, horn)."""
    decomposed = unicodedata.normalize("NFD", text)
    return unicodedata.normalize(
        "NFC", "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    )


def edit_distance(reference: Sequence, hypothesis: Sequence) -> int:
    """Levenshtein distance: fewest insertions, deletions and substitutions."""
    if len(reference) < len(hypothesis):
        reference, hypothesis = hypothesis, reference
    previous = list(range(len(hypothesis) + 1))
    for row, reference_item in enumerate(reference, start=1):
        current = [row]
        for column, hypothesis_item in enumerate(hypothesis, start=1):
            substitution = previous[column - 1] + (reference_item != hypothesis_item)
            current.append(
                min(substitution, previous[column] + 1, current[column - 1] + 1)
            )
        previous = current
    return previous[-1]


def align(reference: Sequence, hypothesis: Sequence) -> list[tuple[str, int, int]]:
    """A minimal edit script from ``reference`` to ``hypothesis``.

    Returns ``(operation, reference_index, hypothesis_index)`` steps, where the
    operation is ``equal``, ``substitute``, ``delete`` (reference item missing
    from the hypothesis) or ``insert`` (extra hypothesis item). The index that
    does not apply to a ``delete``/``insert`` is the position it happens at.
    """
    rows, columns = len(reference) + 1, len(hypothesis) + 1
    table = [[0] * columns for _ in range(rows)]
    for row in range(rows):
        table[row][0] = row
    for column in range(columns):
        table[0][column] = column
    for row in range(1, rows):
        for column in range(1, columns):
            table[row][column] = min(
                table[row - 1][column - 1]
                + (reference[row - 1] != hypothesis[column - 1]),
                table[row - 1][column] + 1,
                table[row][column - 1] + 1,
            )

    steps = []
    row, column = len(reference), len(hypothesis)
    while row > 0 or column > 0:
        if row > 0 and column > 0:
            same = reference[row - 1] == hypothesis[column - 1]
            if table[row][column] == table[row - 1][column - 1] + (not same):
                steps.append(("equal" if same else "substitute", row - 1, column - 1))
                row, column = row - 1, column - 1
                continue
        if row > 0 and table[row][column] == table[row - 1][column] + 1:
            steps.append(("delete", row - 1, column))
            row -= 1
        else:
            steps.append(("insert", row, column - 1))
            column -= 1
    steps.reverse()
    return steps


def rate(errors: int, reference_length: int) -> float | None:
    return errors / reference_length if reference_length else None


def page_counts(reference: str, hypothesis: str) -> dict:
    """Edit distances and reference lengths behind the four rates of a page."""
    reference_nfc, hypothesis_nfc = nfc(reference), nfc(hypothesis)
    unchanged_by_nfc = reference_nfc == reference and hypothesis_nfc == hypothesis

    char_errors_raw = edit_distance(reference, hypothesis)
    word_errors_raw = edit_distance(reference.split(), hypothesis.split())
    return {
        "characters_gt": len(reference),
        "characters_gt_nfc": len(reference_nfc),
        "words_gt": len(reference.split()),
        "char_errors_raw": char_errors_raw,
        "char_errors_nfc": char_errors_raw
        if unchanged_by_nfc
        else edit_distance(reference_nfc, hypothesis_nfc),
        "word_errors_raw": word_errors_raw,
        "word_errors_nfc": word_errors_raw
        if unchanged_by_nfc
        else edit_distance(reference_nfc.split(), hypothesis_nfc.split()),
    }


def rates(counts: dict) -> dict:
    return {
        "cer_raw": rate(counts["char_errors_raw"], counts["characters_gt"]),
        "cer_nfc": rate(counts["char_errors_nfc"], counts["characters_gt_nfc"]),
        "wer_raw": rate(counts["word_errors_raw"], counts["words_gt"]),
        "wer_nfc": rate(counts["word_errors_nfc"], counts["words_gt"]),
    }


def is_subsequence(short: str, long: str) -> bool:
    remaining = iter(long)
    return all(character in remaining for character in short)


def classify_word_pair(ground_truth: str, prediction: str) -> str:
    """Error type of one wrong word, or ``unknown`` when it is not clear-cut."""
    if strip_marks(ground_truth) == strip_marks(prediction):
        return "accent"
    if is_subsequence(prediction, ground_truth):
        return "missing_character"
    if is_subsequence(ground_truth, prediction):
        return "extra_character"
    if len(ground_truth) == len(prediction):
        return "substitution"
    return "unknown"


def word_errors(reference: str, hypothesis: str) -> list[dict]:
    """Word-level differences between a page and its prediction, with a type.

    Words are aligned on their NFC form, so two spellings of the same character
    are not an error here; the strings reported are the original ones.
    """
    reference_words, hypothesis_words = reference.split(), hypothesis.split()
    steps = align(
        [nfc(word) for word in reference_words],
        [nfc(word) for word in hypothesis_words],
    )

    # Group consecutive non-matching steps: a merged or split word shows up as
    # a substitution next to a deletion or an insertion.
    runs: list[list[tuple[str, int, int]]] = []
    for index, step in enumerate(steps):
        if step[0] == "equal":
            continue
        if runs and index > 0 and steps[index - 1][0] != "equal":
            runs[-1].append(step)
        else:
            runs.append([step])

    def record(ground_truth: list[int], prediction: list[int], error_type: str, at: int) -> dict:
        start = ground_truth[0] if ground_truth else at
        end = ground_truth[-1] + 1 if ground_truth else at
        return {
            "ground_truth": " ".join(reference_words[i] for i in ground_truth),
            "prediction": " ".join(hypothesis_words[j] for j in prediction),
            "error_type": error_type,
            "context": " ".join(
                reference_words[max(0, start - CONTEXT_WORDS) : end + CONTEXT_WORDS]
            ),
        }

    errors = []
    for run in runs:
        ground_truth = [i for operation, i, _ in run if operation != "insert"]
        prediction = [j for operation, _, j in run if operation != "delete"]
        at = run[0][1]
        joined_truth = "".join(nfc(reference_words[i]) for i in ground_truth)
        joined_prediction = "".join(nfc(hypothesis_words[j]) for j in prediction)

        if ground_truth and prediction and joined_truth == joined_prediction:
            errors.append(record(ground_truth, prediction, "segmentation", at))
        elif all(operation == "substitute" for operation, _, _ in run):
            for _, i, j in run:
                error_type = classify_word_pair(
                    nfc(reference_words[i]), nfc(hypothesis_words[j])
                )
                errors.append(record([i], [j], error_type, i))
        elif not prediction:
            errors.append(record(ground_truth, [], "missing_character", at))
        elif not ground_truth:
            errors.append(record([], prediction, "extra_character", at))
        else:
            errors.append(record(ground_truth, prediction, "unknown", at))
    return errors


def load_predictions(output_root: Path, profile: str, pages: list[tuple[str, int]]) -> dict:
    """Predicted page text for every requested ``(document, page)``."""
    predictions = {}
    for document in sorted({document for document, _ in pages}):
        document_dir = output_root / profile / document
        if not (document_dir / "metadata.json").is_file():
            raise SystemExit(f"No finished OCR output for {profile}/{document}.")
        lines = load_page_lines(document_dir)
        for page in (page for doc, page in pages if doc == document):
            if page not in lines:
                raise SystemExit(f"{profile}/{document} has no page {page}.")
            predictions[(document, page)] = lines_to_text(lines[page])
    return predictions


def format_rate(value: float | None) -> str:
    return "" if value is None else f"{value:.6f}"


def write_csv(path: Path, columns: Sequence[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profiles", nargs="+", default=list(PROFILES))
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
        print(PENDING_MESSAGE)
        return 0

    pages = sorted(ground_truth)
    page_rows, summary_rows, error_rows = [], [], []
    for profile in args.profiles:
        predictions = load_predictions(args.output_root, profile, pages)
        totals: dict[str, int] = {}
        for document, page in pages:
            reference, hypothesis = ground_truth[(document, page)], predictions[(document, page)]
            counts = page_counts(reference, hypothesis)
            for key, value in counts.items():
                totals[key] = totals.get(key, 0) + value
            page_rows.append(
                {
                    "profile": profile,
                    "document": document,
                    "page": page,
                    **counts,
                    **{key: format_rate(value) for key, value in rates(counts).items()},
                }
            )
            for error in word_errors(reference, hypothesis):
                error_rows.append(
                    {"document": document, "page": page, "profile": profile, **error}
                )
        summary_rows.append(
            {
                "profile": profile,
                "pages": len(pages),
                "characters_gt": totals["characters_gt"],
                "words_gt": totals["words_gt"],
                **{f"micro_{key}": format_rate(value) for key, value in rates(totals).items()},
            }
        )

    write_csv(args.results_dir / "metrics.csv", PAGE_COLUMNS, page_rows)
    write_csv(args.results_dir / "metrics_summary.csv", SUMMARY_COLUMNS, summary_rows)
    write_text(
        args.results_dir / "errors.jsonl",
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in error_rows),
    )

    print(f"verified pages scored: {len(pages)}")
    for row in summary_rows:
        print(
            f"{row['profile']}: micro CER raw={row['micro_cer_raw']} nfc={row['micro_cer_nfc']} | "
            f"micro WER raw={row['micro_wer_raw']} nfc={row['micro_wer_nfc']}"
        )
    print(f"wrote {args.results_dir}/metrics.csv, metrics_summary.csv, errors.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())

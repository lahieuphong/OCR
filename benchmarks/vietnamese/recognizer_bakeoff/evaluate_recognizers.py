#!/usr/bin/env python3
"""Score PP-OCRv6 and VietOCR on the human-verified line crops.

Usage:
    python benchmarks/vietnamese/recognizer_bakeoff/evaluate_recognizers.py

Only rows of ``annotation/manifest.tsv`` with ``verified=true`` are scored.
Both recognizers read the same crops and are compared with the same ground
truth, so line segmentation cannot favour either of them. The run fails if the
two prediction files do not cover exactly the same crops.

Per recognizer, on the verified lines:

    CER / WER            raw and after Unicode NFC, micro-averaged (summed edit
                         distance over summed ground-truth length), computed as
                         in ``../evaluate.py``; nothing else is normalised
    exact line           share of lines predicted exactly
    missing characters   of the ground-truth occurrences of the letters the
                         PP-OCRv6 dictionary lacks, the share recognised
    other characters     the same for every other ground-truth character
    hard cases           of the ground-truth occurrences of ``../hard_cases.txt``
                         entries, the share recognised exactly

An occurrence counts as recognised when the character-level alignment of
ground truth and prediction (both NFC) pairs it with the same character.

Outputs, in ``results/``: ``recognizer_metrics.csv``, ``recognizer_lines.csv``,
``missing_characters.csv`` and ``recognizer_hard_cases.csv``. Without verified
rows nothing is computed.
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path
from typing import Callable

import bakeoff_common as bakeoff
from analyze_hard_cases import MAX_EXAMPLES, judge_page, load_hard_cases
from audit_charset import PPOCRV6_DICT, audit, code_point
from common import HARD_CASES_FILE
from evaluate import PENDING_MESSAGE, align, format_rate, nfc, page_counts, rate, rates, write_csv

RECOGNIZERS = (bakeoff.PPOCR, bakeoff.VIETOCR)
# Below this many verified lines no recommendation is made.
MIN_VERIFIED_LINES = 100
BOOTSTRAP_SAMPLES = 2000
BOOTSTRAP_SEED = 20261008

SUMMARY_COLUMNS = (
    "recognizer",
    "verified_lines",
    "characters_gt",
    "words_gt",
    "micro_cer_raw",
    "micro_cer_nfc",
    "micro_wer_raw",
    "micro_wer_nfc",
    "exact_line_raw",
    "exact_line_nfc",
    "missing_char_occurrences",
    "missing_char_correct",
    "missing_char_accuracy",
    "other_char_occurrences",
    "other_char_correct",
    "other_char_accuracy",
    "hard_case_occurrences",
    "hard_case_correct",
    "hard_case_accuracy",
)
LINE_COLUMNS = (
    "id",
    "document",
    "page",
    "recognizer",
    "characters_gt",
    "words_gt",
    "char_errors_raw",
    "char_errors_nfc",
    "word_errors_raw",
    "word_errors_nfc",
    "exact_raw",
    "exact_nfc",
)
MISSING_COLUMNS = (
    "char",
    "unicode",
    "occurrences",
    "ppocr_correct",
    "ppocr_accuracy",
    "vietocr_correct",
    "vietocr_accuracy",
)
HARD_CASE_COLUMNS = ("word", "occurrences_in_gt", "ppocr_correct", "vietocr_correct", "example_errors")


def character_hits(reference: str, hypothesis: str) -> list[tuple[str, bool]]:
    """Each ground-truth character with whether the prediction got it right."""
    reference, hypothesis = nfc(reference), nfc(hypothesis)
    return [
        (reference[index], operation == "equal")
        for operation, index, _ in align(reference, hypothesis)
        if operation != "insert"
    ]


def score_line(reference: str, hypothesis: str, missing: set[str], cases: list[str]) -> dict:
    """Everything counted for one recognizer on one line."""
    hits = character_hits(reference, hypothesis)
    per_character: dict[str, list[int]] = {}
    for character, correct in hits:
        if character in missing:
            tally = per_character.setdefault(character, [0, 0])
            tally[0] += 1
            tally[1] += correct
    verdicts = judge_page(reference, hypothesis, cases)
    return {
        **page_counts(reference, hypothesis),
        "exact_raw": int(hypothesis == reference),
        "exact_nfc": int(nfc(hypothesis) == nfc(reference)),
        "missing_char_occurrences": sum(character in missing for character, _ in hits),
        "missing_char_correct": sum(correct for character, correct in hits if character in missing),
        "other_char_occurrences": sum(character not in missing for character, _ in hits),
        "other_char_correct": sum(correct for character, correct in hits if character not in missing),
        "hard_case_occurrences": sum(len(entries) for entries in verdicts.values()),
        "hard_case_correct": sum(entry is None for entries in verdicts.values() for entry in entries),
        "per_missing_character": per_character,
        "hard_case_verdicts": verdicts,
    }


def total(lines: list[dict], key: str) -> int:
    return sum(line[key] for line in lines)


def summarise(recognizer: str, lines: list[dict]) -> dict:
    counts = {
        key: total(lines, key)
        for key in (
            "characters_gt", "characters_gt_nfc", "words_gt",
            "char_errors_raw", "char_errors_nfc", "word_errors_raw", "word_errors_nfc",
        )
    }  # fmt: skip
    summary = {
        "recognizer": recognizer,
        "verified_lines": len(lines),
        "characters_gt": counts["characters_gt"],
        "words_gt": counts["words_gt"],
        **{f"micro_{name}": value for name, value in rates(counts).items()},
        "exact_line_raw": rate(total(lines, "exact_raw"), len(lines)),
        "exact_line_nfc": rate(total(lines, "exact_nfc"), len(lines)),
    }
    for group in ("missing_char", "other_char", "hard_case"):
        occurrences = total(lines, f"{group}_occurrences")
        correct = total(lines, f"{group}_correct")
        summary[f"{group}_occurrences"] = occurrences
        summary[f"{group}_correct"] = correct
        summary[f"{group}_accuracy"] = rate(correct, occurrences)
    return summary


def cer_nfc(lines: list[dict]) -> float | None:
    return rate(total(lines, "char_errors_nfc"), total(lines, "characters_gt_nfc"))


def accuracy(group: str) -> Callable[[list[dict]], float | None]:
    return lambda lines: rate(total(lines, f"{group}_correct"), total(lines, f"{group}_occurrences"))


def paired_difference(
    first: list[dict], second: list[dict], statistic: Callable[[list[dict]], float | None]
) -> tuple[float, float, float] | None:
    """``statistic(first) - statistic(second)`` with a 95% paired bootstrap interval.

    ``first`` and ``second`` hold the same lines in the same order; lines are
    resampled together, so the interval reflects line-to-line variation and not
    the difficulty of the sample.
    """
    observed_first, observed_second = statistic(first), statistic(second)
    if observed_first is None or observed_second is None:
        return None
    rng = random.Random(BOOTSTRAP_SEED)
    differences = []
    for _ in range(BOOTSTRAP_SAMPLES):
        sample = [rng.randrange(len(first)) for _ in first]
        a = statistic([first[i] for i in sample])
        b = statistic([second[i] for i in sample])
        if a is not None and b is not None:
            differences.append(a - b)
    differences.sort()
    low = differences[int(0.025 * len(differences))]
    high = differences[min(len(differences) - 1, int(0.975 * len(differences)))]
    return observed_first - observed_second, low, high


def decide(scores: dict[str, list[dict]], minimum_lines: int) -> list[str]:
    """The decision rule of the bake-off, as printable lines.

    VietOCR is recommended when its CER is significantly lower *and* its
    accuracy on the missing letters is clearly higher. Otherwise PP-OCRv6 with
    an extended dictionary is recommended when it holds its own on every other
    character. "Significantly" means the 95% paired bootstrap interval of the
    difference excludes zero.
    """
    ppocr, vietocr = scores[bakeoff.PPOCR], scores[bakeoff.VIETOCR]
    if len(ppocr) < minimum_lines:
        return [
            f"WINNER: NOT DECIDED ({len(ppocr)} verified lines, at least {minimum_lines} needed)"
        ]

    def describe(label: str, difference: tuple[float, float, float] | None) -> str:
        if difference is None:
            return f"{label}: not measurable on this ground truth"
        value, low, high = difference
        return f"{label}: {value:+.4f} (95% interval {low:+.4f} .. {high:+.4f})"

    cer = paired_difference(vietocr, ppocr, cer_nfc)
    missing = paired_difference(vietocr, ppocr, accuracy("missing_char"))
    other = paired_difference(ppocr, vietocr, accuracy("other_char"))
    vietocr_cer_lower = cer is not None and cer[2] < 0
    vietocr_missing_higher = missing is not None and missing[1] > 0
    # Competitive: not significantly worse than VietOCR on the other characters.
    ppocr_competitive = other is not None and other[2] >= 0

    report = [
        describe("CER (NFC), VietOCR minus PP-OCRv6", cer),
        describe("missing-character accuracy, VietOCR minus PP-OCRv6", missing),
        describe("other-character accuracy, PP-OCRv6 minus VietOCR", other),
        f"VietOCR CER significantly lower:              {'yes' if vietocr_cer_lower else 'no'}",
        f"VietOCR missing-character accuracy higher:    {'yes' if vietocr_missing_higher else 'no'}",
        f"PP-OCRv6 competitive on the other characters: {'yes' if ppocr_competitive else 'no'}",
    ]
    if vietocr_cer_lower and vietocr_missing_higher:
        report.append("RECOMMENDATION: PaddleOCR detection + VietOCR recognition; fine-tune VietOCR first")
    elif ppocr_competitive:
        report.append(
            "RECOMMENDATION: extended PP-OCRv6 dictionary + checkpoint head migration + fine-tune"
        )
    else:
        report.append("RECOMMENDATION: none; neither condition of the decision rule is met")
    return report


def missing_character_rows(scores: dict[str, list[dict]], missing: list[str]) -> list[dict]:
    rows = []
    for character in missing:
        tallies = {
            name: [
                sum(line["per_missing_character"].get(character, [0, 0])[i] for line in lines)
                for i in (0, 1)
            ]
            for name, lines in scores.items()
        }
        occurrences = tallies[bakeoff.PPOCR][0]
        rows.append(
            {
                "char": character,
                "unicode": code_point(character),
                "occurrences": occurrences,
                "ppocr_correct": tallies[bakeoff.PPOCR][1],
                "ppocr_accuracy": format_rate(rate(tallies[bakeoff.PPOCR][1], occurrences)),
                "vietocr_correct": tallies[bakeoff.VIETOCR][1],
                "vietocr_accuracy": format_rate(rate(tallies[bakeoff.VIETOCR][1], occurrences)),
            }
        )
    return rows


def hard_case_rows(scores: dict[str, list[dict]], cases: list[str]) -> list[dict]:
    rows = []
    for case in cases:
        entries = {
            name: [entry for line in lines for entry in line["hard_case_verdicts"][case]]
            for name, lines in scores.items()
        }
        examples = []
        for name in RECOGNIZERS:
            wrong = [entry for entry in entries[name] if entry is not None]
            examples.extend(f"{name}: {example}" for example in list(dict.fromkeys(wrong))[:MAX_EXAMPLES])
        rows.append(
            {
                "word": case,
                "occurrences_in_gt": len(entries[bakeoff.PPOCR]),
                "ppocr_correct": sum(entry is None for entry in entries[bakeoff.PPOCR]),
                "vietocr_correct": sum(entry is None for entry in entries[bakeoff.VIETOCR]),
                "example_errors": " | ".join(examples),
            }
        )
    return rows


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--annotation", type=Path, default=bakeoff.ANNOTATION_MANIFEST)
    parser.add_argument("--ppocr", type=Path, default=bakeoff.PREDICTION_FILES[bakeoff.PPOCR])
    parser.add_argument("--vietocr", type=Path, default=bakeoff.PREDICTION_FILES[bakeoff.VIETOCR])
    parser.add_argument("--dict", type=Path, default=PPOCRV6_DICT, dest="dictionary")
    parser.add_argument("--hard-cases", type=Path, default=HARD_CASES_FILE)
    parser.add_argument("--results-dir", type=Path, default=bakeoff.RESULTS_DIR)
    parser.add_argument("--min-verified", type=int, default=MIN_VERIFIED_LINES)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    predictions = {
        bakeoff.PPOCR: bakeoff.load_predictions(args.ppocr),
        bakeoff.VIETOCR: bakeoff.load_predictions(args.vietocr),
    }
    bakeoff.check_same_ids({name: set(rows) for name, rows in predictions.items()})
    print(f"recognizer ids: both cover the same {len(predictions[bakeoff.PPOCR])} crops")

    annotation = bakeoff.read_annotation(args.annotation)
    verified = [row for row in annotation if bakeoff.is_verified(row)]
    unknown = [row["id"] for row in verified if row["id"] not in predictions[bakeoff.PPOCR]]
    if unknown:
        raise SystemExit(f"FAIL: verified rows without a prediction: {', '.join(unknown[:5])}")
    print(f"verified lines: {len(verified)} of {len(annotation)} selected")
    if not verified:
        print(PENDING_MESSAGE)
        print("\n".join(decide({name: [] for name in RECOGNIZERS}, args.min_verified)))
        return 0

    missing = audit(args.dictionary)["missing"]
    cases = load_hard_cases(args.hard_cases)
    scores = {
        name: [
            score_line(row["ground_truth"], predictions[name][row["id"]]["prediction"], set(missing), cases)
            for row in verified
        ]
        for name in RECOGNIZERS
    }
    summaries = [summarise(name, scores[name]) for name in RECOGNIZERS]

    write_csv(
        args.results_dir / "recognizer_metrics.csv",
        SUMMARY_COLUMNS,
        [
            {key: format_rate(value) if isinstance(value, float) or value is None else value
             for key, value in summary.items()}
            for summary in summaries
        ],
    )  # fmt: skip
    write_csv(
        args.results_dir / "recognizer_lines.csv",
        LINE_COLUMNS,
        [
            {"id": row["id"], "document": row["document"], "page": row["page"], "recognizer": name,
             **{column: line[column] for column in LINE_COLUMNS[4:]}}
            for name in RECOGNIZERS
            for row, line in zip(verified, scores[name])
        ],
    )  # fmt: skip
    write_csv(
        args.results_dir / "missing_characters.csv", MISSING_COLUMNS, missing_character_rows(scores, missing)
    )
    write_csv(
        args.results_dir / "recognizer_hard_cases.csv", HARD_CASE_COLUMNS, hard_case_rows(scores, cases)
    )

    def share(summary: dict, group: str) -> str:
        return (
            f"{summary[f'{group}_correct']}/{summary[f'{group}_occurrences']}"
            f" ({format_rate(summary[f'{group}_accuracy']) or 'n/a'})"
        )

    for summary in summaries:
        print(
            f"{summary['recognizer']}: "
            f"CER raw={format_rate(summary['micro_cer_raw'])} nfc={format_rate(summary['micro_cer_nfc'])} | "
            f"WER raw={format_rate(summary['micro_wer_raw'])} nfc={format_rate(summary['micro_wer_nfc'])} | "
            f"exact line raw={format_rate(summary['exact_line_raw'])} nfc={format_rate(summary['exact_line_nfc'])}"
        )
        print(
            f"  missing characters {share(summary, 'missing_char')} | "
            f"other characters {share(summary, 'other_char')} | hard cases {share(summary, 'hard_case')}"
        )
    print("\n".join(decide(scores, args.min_verified)))
    print(f"wrote {args.results_dir}/recognizer_metrics.csv, recognizer_lines.csv, "
          "missing_characters.csv, recognizer_hard_cases.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())

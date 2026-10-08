#!/usr/bin/env python3
"""Score PP-OCRv6 and VietOCR on the human-verified line crops.

Usage:
    python benchmarks/vietnamese/recognizer_bakeoff/evaluate_recognizers.py

Only rows of ``annotation/manifest.tsv`` with ``verified=true`` are scored;
rows a person set aside (``excluded_reason``) never are. Both recognizers read
the same crops and are compared with the same ground truth, so line
segmentation cannot favour either of them. The run fails if the two prediction
files do not cover exactly the same crops.

Per recognizer, on the verified lines:

    CER / WER            raw and after Unicode NFC, micro-averaged (summed edit
                         distance over summed ground-truth length), computed as
                         in ``../evaluate.py``; nothing else is normalised
    exact line           share of lines predicted exactly
    missing characters   of the ground-truth occurrences of the letters the
                         PP-OCRv6 dictionary lacks (``../audit_charset.py``),
                         the share recognised
    other characters     the same for every other ground-truth character
    hard cases           of the ground-truth occurrences of ``../hard_cases.txt``
                         entries, the share recognised exactly

An occurrence counts as recognised when the character-level alignment of
ground truth and prediction (both NFC) pairs it with the same character.

Three further views of the same lines:

    paired         per line, which recognizer has fewer character errors, and
                   the difference in CER with a 95% paired bootstrap interval
    line length    CER per group of crop aspect ratio (width / height). VietOCR
                   resizes to 32 px high and at most 512 px wide, so it squeezes
                   every crop wider than 16:1:
                       short   up to 16:1      not squeezed
                       medium  16:1 to 24:1    squeezed by up to 1.5x
                       long    over 24:1       squeezed by more than 1.5x
    edge insertions  lines where a prediction carries text before the start or
                   after the end of the ground truth (see ``edge_insertion``)
    error types    substitutions, deletions and insertions behind the CER
    by source      the same metrics split by how each line was verified: the
                   annotator accepted the PP-OCRv6 text, accepted the VietOCR
                   text, or typed it. A recognizer scores zero errors on the
                   lines accepted from it by construction, so the typed lines
                   are the ones where neither prediction was taken as it stood.

Outputs go to ``results/``. Without verified rows nothing is computed.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import unicodedata
from collections import Counter
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
HEAD_ANALYSIS = bakeoff.RESULTS_DIR / "ppocrv6_head_analysis.json"

# Upper bound (inclusive) of each group of crop aspect ratio.
LENGTH_GROUPS = (("short", 16.0), ("medium", 24.0), ("long", float("inf")))
# An edge insertion is reported only when it is unmistakable: at least this
# many visible characters of extra text, next to a line that is otherwise
# recognised (the rest differs from the ground truth by at most this share).
EDGE_MIN_CHARACTERS = 3
EDGE_MAX_REST_ERROR = 0.5

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
    "lines_with_edge_insertion",
    "substitutions",
    "deletions",
    "insertions",
)
LINE_COLUMNS = (
    "id",
    "document",
    "page",
    "length_group",
    "recognizer",
    "characters_gt",
    "words_gt",
    "char_errors_raw",
    "char_errors_nfc",
    "word_errors_raw",
    "word_errors_nfc",
    "exact_raw",
    "exact_nfc",
    "edge_insertion",
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
LENGTH_COLUMNS = ("length_group", "recognizer", "lines", "characters_gt", "micro_cer_nfc", "micro_wer_nfc")
SOURCE_COLUMNS = (
    "ground_truth_source", "recognizer", "lines", "characters_gt", "micro_cer_nfc", "micro_wer_nfc", "exact_line_nfc",
)  # fmt: skip
EDIT_OPERATIONS = {"substitute": "substitutions", "delete": "deletions", "insert": "insertions"}
EDGE_COLUMNS = ("id", "recognizer", "edge", "extra_text", "ground_truth", "prediction")
ERROR_COLUMNS = (
    "id",
    "length_group",
    "ground_truth",
    "ppocr_prediction",
    "ppocr_char_errors",
    "vietocr_prediction",
    "vietocr_char_errors",
)


def character_hits(reference: str, hypothesis: str) -> list[tuple[str, bool]]:
    """Each ground-truth character with whether the prediction got it right."""
    reference, hypothesis = nfc(reference), nfc(hypothesis)
    return [
        (reference[index], operation == "equal")
        for operation, index, _ in align(reference, hypothesis)
        if operation != "insert"
    ]


def edit_operations(reference: str, hypothesis: str) -> dict[str, int]:
    """How many substitutions, deletions and insertions turn the truth into the prediction."""
    counts = Counter(operation for operation, _, _ in align(nfc(reference), nfc(hypothesis)))
    return {name: counts[operation] for operation, name in EDIT_OPERATIONS.items()}


def prefix_distances(reference: str, hypothesis: str) -> list[int]:
    """Edit distance between ``reference`` and each prefix of ``hypothesis``."""
    previous = list(range(len(hypothesis) + 1))
    for row, reference_item in enumerate(reference, start=1):
        current = [row]
        for column, hypothesis_item in enumerate(hypothesis, start=1):
            current.append(
                min(
                    previous[column - 1] + (reference_item != hypothesis_item),
                    previous[column] + 1,
                    current[column - 1] + 1,
                )
            )
        previous = current
    return previous


def trailing_extra(reference: str, hypothesis: str) -> str:
    """Text of ``hypothesis`` after the point where it best matches all of ``reference``.

    Among the prefixes of the hypothesis closest to the reference the longest
    one is taken, so a wrong last character counts as a substitution and not
    as inserted text.
    """
    distances = prefix_distances(reference, hypothesis)
    best = min(distances)
    end = max(index for index, distance in enumerate(distances) if distance == best)
    extra = hypothesis[end:]
    visible = sum(not character.isspace() for character in extra)
    if visible >= EDGE_MIN_CHARACTERS and best <= EDGE_MAX_REST_ERROR * len(reference):
        return extra
    return ""


def edge_insertion(reference: str, hypothesis: str) -> dict[str, str]:
    """Clear extra text at the start (``prefix``) and at the end (``suffix``) of a prediction."""
    reference, hypothesis = nfc(reference), nfc(hypothesis)
    return {
        "prefix": trailing_extra(reference[::-1], hypothesis[::-1])[::-1],
        "suffix": trailing_extra(reference, hypothesis),
    }


def length_group(crop_width: int, crop_height: int) -> str:
    aspect = crop_width / crop_height
    return next(name for name, upper in LENGTH_GROUPS if aspect <= upper)


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
    edges = edge_insertion(reference, hypothesis)
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
        "edges": edges,
        "edge_insertion": int(any(edges.values())),
        **edit_operations(reference, hypothesis),
    }


def total(lines: list[dict], key: str) -> int:
    return sum(line[key] for line in lines)


def error_counts(lines: list[dict]) -> dict:
    return {
        key: total(lines, key)
        for key in (
            "characters_gt", "characters_gt_nfc", "words_gt",
            "char_errors_raw", "char_errors_nfc", "word_errors_raw", "word_errors_nfc",
        )
    }  # fmt: skip


def summarise(recognizer: str, lines: list[dict]) -> dict:
    counts = error_counts(lines)
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
    summary["lines_with_edge_insertion"] = total(lines, "edge_insertion")
    for name in EDIT_OPERATIONS.values():
        summary[name] = total(lines, name)
    return summary


def cer_nfc(lines: list[dict]) -> float | None:
    return rate(total(lines, "char_errors_nfc"), total(lines, "characters_gt_nfc"))


def wer_nfc(lines: list[dict]) -> float | None:
    return rate(total(lines, "word_errors_nfc"), total(lines, "words_gt"))


def accuracy(group: str) -> Callable[[list[dict]], float | None]:
    return lambda lines: rate(total(lines, f"{group}_correct"), total(lines, f"{group}_occurrences"))


def paired_difference(
    first: list[dict], second: list[dict], statistic: Callable[[list[dict]], float | None]
) -> dict | None:
    """``statistic(first) - statistic(second)`` with a 95% paired bootstrap interval.

    ``first`` and ``second`` hold the same lines in the same order; lines are
    resampled together, so the interval reflects line-to-line variation and not
    the difficulty of the sample.
    """
    observed_first, observed_second = statistic(first), statistic(second)
    if not first or observed_first is None or observed_second is None:
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
    return {
        "difference": observed_first - observed_second,
        "low": differences[int(0.025 * len(differences))],
        "high": differences[min(len(differences) - 1, int(0.975 * len(differences)))],
    }


def paired_lines(scores: dict[str, list[dict]]) -> dict:
    """Line by line: who makes fewer character errors, and by how much CER."""
    ppocr, vietocr = scores[bakeoff.PPOCR], scores[bakeoff.VIETOCR]
    deltas = [
        (v["char_errors_nfc"] - p["char_errors_nfc"]) / p["characters_gt_nfc"]
        for p, v in zip(ppocr, vietocr)
        if p["characters_gt_nfc"]
    ]
    return {
        "ppocr_wins": sum(p["char_errors_nfc"] < v["char_errors_nfc"] for p, v in zip(ppocr, vietocr)),
        "vietocr_wins": sum(v["char_errors_nfc"] < p["char_errors_nfc"] for p, v in zip(ppocr, vietocr)),
        "ties": sum(p["char_errors_nfc"] == v["char_errors_nfc"] for p, v in zip(ppocr, vietocr)),
        # Per-line CER of VietOCR minus that of PP-OCRv6: negative favours VietOCR.
        "mean_cer_delta": statistics.fmean(deltas) if deltas else None,
        "median_cer_delta": statistics.median(deltas) if deltas else None,
        "micro_cer_delta": paired_difference(vietocr, ppocr, cer_nfc),
    }


def head_migration_feasible(path: Path) -> bool | None:
    """Outcome of ``inspect_rec_checkpoint.py``, or None when it has not been run."""
    if not path.is_file():
        return None
    check = json.loads(path.read_text(encoding="utf-8"))["migration_check"]
    return check["max_feature_difference"] == 0 and check["max_old_class_logit_difference"] == 0


def decide(scores: dict[str, list[dict]], groups: list[str], head_feasible: bool | None, minimum: int) -> dict:
    """The decision rule of the bake-off.

    VietOCR is chosen when its CER is clearly lower, its WER is lower, its
    accuracy on the missing letters is far higher, and long lines do not turn
    the result around. A custom PP-OCRv6 is chosen when PP-OCRv6 is close
    overall, its errors sit in the missing letters, VietOCR is clearly worse on
    long lines, and the head migration was shown to work. Anything else is
    inconclusive: annotate the remaining lines and evaluate again.

    "Clearly" means the 95% paired bootstrap interval of the difference
    excludes zero.
    """
    ppocr, vietocr = scores[bakeoff.PPOCR], scores[bakeoff.VIETOCR]
    if len(ppocr) < minimum:
        return {
            "verdict": "NOT DECIDED",
            "report": [f"WINNER: NOT DECIDED ({len(ppocr)} verified lines, at least {minimum} needed)"],
        }

    def of_group(lines: list[dict], name: str) -> list[dict]:
        return [line for line, group in zip(lines, groups) if group == name]

    differences = {
        "cer": paired_difference(vietocr, ppocr, cer_nfc),
        "wer": paired_difference(vietocr, ppocr, wer_nfc),
        "missing": paired_difference(vietocr, ppocr, accuracy("missing_char")),
        "other": paired_difference(ppocr, vietocr, accuracy("other_char")),
        "long_cer": paired_difference(of_group(vietocr, "long"), of_group(ppocr, "long"), cer_nfc),
    }

    def below_zero(name: str) -> bool:
        return differences[name] is not None and differences[name]["high"] < 0

    def above_zero(name: str) -> bool:
        return differences[name] is not None and differences[name]["low"] > 0

    conditions = {
        "vietocr": {
            "CER clearly lower than PP-OCRv6": below_zero("cer"),
            "WER lower than PP-OCRv6": differences["wer"] is not None and differences["wer"]["difference"] < 0,
            "accuracy on the missing letters far higher": above_zero("missing"),
            "not clearly worse than PP-OCRv6 on long lines": not above_zero("long_cer"),
        },
        "custom_ppocr": {
            "PP-OCRv6 close to VietOCR overall": not below_zero("cer"),
            "PP-OCRv6 errors concentrated in the missing letters": not below_zero("other"),
            "VietOCR clearly worse on long lines": above_zero("long_cer"),
            "head migration shown to work": head_feasible is True,
        },
    }
    if all(conditions["vietocr"].values()):
        verdict = "VIETOCR"
        conclusion = "RECOMMENDATION: PP-OCRv6_medium_det -> line crops -> VietOCR recognizer"
    elif all(conditions["custom_ppocr"].values()):
        verdict = "CUSTOM PP-OCRV6"
        conclusion = (
            "RECOMMENDATION: PP-OCRv6_medium_det -> PP-OCRv6_medium_rec with the extended "
            "Vietnamese charset, a migrated head and fine-tuning"
        )
    else:
        verdict = "INCONCLUSIVE"
        conclusion = "RECOMMENDATION: none yet; verify the remaining lines and evaluate again"

    labels = {
        "cer": "CER (NFC), VietOCR minus PP-OCRv6",
        "wer": "WER (NFC), VietOCR minus PP-OCRv6",
        "missing": "missing-character accuracy, VietOCR minus PP-OCRv6",
        "other": "other-character accuracy, PP-OCRv6 minus VietOCR",
        "long_cer": "CER (NFC) on long lines, VietOCR minus PP-OCRv6",
    }
    report = []
    for name, label in labels.items():
        value = differences[name]
        report.append(
            f"{label}: not measurable on these lines"
            if value is None
            else f"{label}: {value['difference']:+.4f} (95% interval {value['low']:+.4f} .. {value['high']:+.4f})"
        )
    for side, title in (("vietocr", "VietOCR"), ("custom_ppocr", "custom PP-OCRv6")):
        report.append(f"conditions for {title}:")
        report.extend(f"  [{'x' if met else ' '}] {name}" for name, met in conditions[side].items())
    report.append(conclusion)
    return {"verdict": verdict, "differences": differences, "conditions": conditions, "report": report}


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


def length_group_rows(scores: dict[str, list[dict]], groups: list[str]) -> list[dict]:
    return group_rows(scores, groups, [name for name, _ in LENGTH_GROUPS], "length_group")


def group_rows(scores: dict[str, list[dict]], labels: list[str], names: list[str], column: str) -> list[dict]:
    """The headline rates of each recognizer on each named subset of the lines."""
    rows = []
    for name in names:
        for recognizer in RECOGNIZERS:
            lines = [line for line, label in zip(scores[recognizer], labels) if label == name]
            rows.append(
                {
                    column: name,
                    "recognizer": recognizer,
                    "lines": len(lines),
                    "characters_gt": total(lines, "characters_gt"),
                    "micro_cer_nfc": cer_nfc(lines),
                    "micro_wer_nfc": wer_nfc(lines),
                    "exact_line_nfc": rate(total(lines, "exact_nfc"), len(lines)),
                }
            )
    return rows


def usable_rows(annotation: list[dict]) -> tuple[list[dict], list[str]]:
    """Verified rows whose ground truth is still the text that was verified."""
    usable, rejected = [], []
    for row in annotation:
        if not bakeoff.is_verified(row):
            continue
        if not row["ground_truth"]:
            rejected.append(f"{row['id']}: verified without ground truth")
        elif row["ground_truth_sha256"] != bakeoff.text_sha256(row["ground_truth"]):
            rejected.append(f"{row['id']}: ground truth changed after it was verified")
        else:
            usable.append(row)
    return usable, rejected


def formatted(row: dict) -> dict:
    return {
        key: format_rate(value) if isinstance(value, float) or value is None else value
        for key, value in row.items()
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--annotation", type=Path, default=bakeoff.ANNOTATION_MANIFEST)
    parser.add_argument("--manifest", type=Path, default=bakeoff.MANIFEST)
    parser.add_argument("--ppocr", type=Path, default=bakeoff.PREDICTION_FILES[bakeoff.PPOCR])
    parser.add_argument("--vietocr", type=Path, default=bakeoff.PREDICTION_FILES[bakeoff.VIETOCR])
    parser.add_argument("--dict", type=Path, default=PPOCRV6_DICT, dest="dictionary")
    parser.add_argument("--hard-cases", type=Path, default=HARD_CASES_FILE)
    parser.add_argument("--head-analysis", type=Path, default=HEAD_ANALYSIS)
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
    verified, rejected = usable_rows(annotation)
    for reason in rejected:
        print(f"not scored: {reason}")
    unknown = [row["id"] for row in verified if row["id"] not in predictions[bakeoff.PPOCR]]
    if unknown:
        raise SystemExit(f"FAIL: verified rows without a prediction: {', '.join(unknown[:5])}")
    skipped = [row for row in annotation if bakeoff.is_excluded(row)]
    print(
        f"verified lines: {len(verified)} of {len(annotation)} selected "
        f"({len(skipped)} set aside, {len(verified) + len(skipped)} inspected)"
    )
    if not verified:
        print(PENDING_MESSAGE)
        print("\n".join(decide({name: [] for name in RECOGNIZERS}, [], None, args.min_verified)["report"]))
        return 0

    crops = {row["id"]: row for row in bakeoff.load_manifest(args.manifest)}
    groups = [length_group(crops[row["id"]]["crop_width"], crops[row["id"]]["crop_height"]) for row in verified]
    missing = audit(args.dictionary)["missing"]
    cases = load_hard_cases(args.hard_cases)
    texts = {name: [predictions[name][row["id"]]["prediction"] for row in verified] for name in RECOGNIZERS}
    scores = {
        name: [
            score_line(row["ground_truth"], text, set(missing), cases)
            for row, text in zip(verified, texts[name])
        ]
        for name in RECOGNIZERS
    }
    summaries = [summarise(name, scores[name]) for name in RECOGNIZERS]
    paired = paired_lines(scores)
    lengths = length_group_rows(scores, groups)
    sources = [row["ground_truth_source"] or "unknown" for row in verified]
    by_source = group_rows(scores, sources, sorted(set(sources)), "ground_truth_source")
    decision = decide(scores, groups, head_migration_feasible(args.head_analysis), args.min_verified)

    edge_rows = [
        {
            "id": row["id"],
            "recognizer": name,
            "edge": edge,
            "extra_text": line["edges"][edge],
            "ground_truth": row["ground_truth"],
            "prediction": text,
        }
        for name in RECOGNIZERS
        for row, line, text in zip(verified, scores[name], texts[name])
        for edge in ("prefix", "suffix")
        if line["edges"][edge]
    ]
    error_rows = sorted(
        (
            {
                "id": row["id"],
                "length_group": group,
                "ground_truth": row["ground_truth"],
                "ppocr_prediction": texts[bakeoff.PPOCR][index],
                "ppocr_char_errors": scores[bakeoff.PPOCR][index]["char_errors_nfc"],
                "vietocr_prediction": texts[bakeoff.VIETOCR][index],
                "vietocr_char_errors": scores[bakeoff.VIETOCR][index]["char_errors_nfc"],
            }
            for index, (row, group) in enumerate(zip(verified, groups))
        ),
        key=lambda item: -(item["ppocr_char_errors"] + item["vietocr_char_errors"]),
    )
    ground_truth = {
        "verified_lines": len(verified),
        "characters": summaries[0]["characters_gt"],
        "words": summaries[0]["words_gt"],
        "all_nfc": all(unicodedata.is_normalized("NFC", row["ground_truth"]) for row in verified),
        "documents": sorted({row["document"] for row in verified}),
        "pages": len({(row["document"], row["page"]) for row in verified}),
        "by_source": dict(Counter(row["ground_truth_source"] or "unknown" for row in verified)),
        "by_length_group": dict(Counter(groups)),
        "skipped": len(skipped),
        "skipped_by_reason": dict(Counter(row["excluded_reason"] for row in skipped)),
        "selected": len(annotation),
    }

    results = args.results_dir
    write_csv(results / "recognizer_metrics.csv", SUMMARY_COLUMNS, [formatted(s) for s in summaries])
    write_csv(
        results / "recognizer_lines.csv",
        LINE_COLUMNS,
        [
            {"id": row["id"], "document": row["document"], "page": row["page"], "length_group": group,
             "recognizer": name, **{column: line[column] for column in LINE_COLUMNS[5:]}}
            for name in RECOGNIZERS
            for row, group, line in zip(verified, groups, scores[name])
        ],
    )  # fmt: skip
    write_csv(results / "missing_characters.csv", MISSING_COLUMNS, missing_character_rows(scores, missing))
    write_csv(results / "recognizer_hard_cases.csv", HARD_CASE_COLUMNS, hard_case_rows(scores, cases))
    write_csv(
        results / "line_length_groups.csv",
        LENGTH_COLUMNS,
        [formatted({column: row[column] for column in LENGTH_COLUMNS}) for row in lengths],
    )
    write_csv(
        results / "ground_truth_source_groups.csv", SOURCE_COLUMNS, [formatted(row) for row in by_source]
    )
    write_csv(results / "edge_insertions.csv", EDGE_COLUMNS, edge_rows)
    write_csv(results / "recognizer_errors.csv", ERROR_COLUMNS, error_rows)
    bakeoff.write_json(
        results / "summary.json",
        {
            "ground_truth": ground_truth,
            "recognizers": {summary["recognizer"]: summary for summary in summaries},
            "paired": paired,
            "line_length": lengths,
            "by_ground_truth_source": by_source,
            "edge_insertions": {
                name: {
                    "lines": total(scores[name], "edge_insertion"),
                    "prefix": sum(bool(line["edges"]["prefix"]) for line in scores[name]),
                    "suffix": sum(bool(line["edges"]["suffix"]) for line in scores[name]),
                }
                for name in RECOGNIZERS
            },
            "decision": {key: value for key, value in decision.items() if key != "report"},
        },
    )

    def share(summary: dict, group: str) -> str:
        return (
            f"{summary[f'{group}_correct']}/{summary[f'{group}_occurrences']}"
            f" ({format_rate(summary[f'{group}_accuracy']) or 'n/a'})"
        )

    print(
        f"ground truth: {ground_truth['characters']} characters, {ground_truth['words']} words, "
        f"{len(ground_truth['documents'])} document(s), {ground_truth['pages']} page(s), "
        f"all NFC: {ground_truth['all_nfc']}; verified by: {ground_truth['by_source']}"
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
            f"other characters {share(summary, 'other_char')} | hard cases {share(summary, 'hard_case')} | "
            f"lines with an edge insertion {summary['lines_with_edge_insertion']}"
        )
    print(
        f"paired: PP-OCRv6 better on {paired['ppocr_wins']} line(s), VietOCR on {paired['vietocr_wins']}, "
        f"tied on {paired['ties']}; per-line CER delta (VietOCR - PP-OCRv6) "
        f"mean {paired['mean_cer_delta']:+.4f}, median {paired['median_cer_delta']:+.4f}"
    )
    for row in lengths:
        print(
            f"  {row['length_group']:6s} {row['recognizer']:8s} lines={row['lines']:3d} "
            f"CER nfc={format_rate(row['micro_cer_nfc']) or 'n/a'}"
        )
    for summary in summaries:
        print(
            f"error types, {summary['recognizer']}: {summary['substitutions']} substitution(s), "
            f"{summary['deletions']} deletion(s), {summary['insertions']} insertion(s)"
        )
    for row in by_source:
        print(
            f"  verified as {row['ground_truth_source']:16s} {row['recognizer']:8s} lines={row['lines']:3d} "
            f"CER nfc={format_rate(row['micro_cer_nfc']) or 'n/a'} exact={format_rate(row['exact_line_nfc']) or 'n/a'}"
        )
    print("\n".join(decision["report"]))
    print(f"wrote {results}/summary.json and 8 CSV files")
    return 0


if __name__ == "__main__":
    sys.exit(main())

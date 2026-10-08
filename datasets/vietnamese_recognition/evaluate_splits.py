#!/usr/bin/env python3
"""Score a recognizer on the sets of the dataset, one set at a time.

Usage:
    python datasets/vietnamese_recognition/evaluate_splits.py inputs --output <inputs.jsonl>
    python datasets/vietnamese_recognition/evaluate_splits.py score \\
        --predictions <predictions.jsonl> --label <model or config name>

``inputs`` lists the crops of the sets to predict, in the form
``benchmarks/vietnamese/recognizer_bakeoff/run_vietocr.py --manifest`` reads.
``score`` then reports CER, WER and exact-line accuracy separately for

    real_val             what a model or a setting is chosen on
    synthetic_val        a diagnostic: has the model learnt the synthetic data
    bakeoff_regression   comparison with the bake-off, and known hard lines

and writes them to ``manifests/evaluations/<label>.json``.

The blind test is locked. By default ``inputs`` leaves its crops out and
``score`` does not compute its metrics, even when predictions for it are in
the file. ``--unlock-blind-test`` lifts the lock for one run and records who
looked, when, at which model and why in ``manifests/blind_test_unlocks.jsonl``.
The lock is a procedure, not a protection: its purpose is that nobody tunes
anything on the blind test by accident, and that every look leaves a trace.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import dataset_common as dataset
from dataset_common import BAKEOFF_REGRESSION, BLIND_TEST, REAL_VAL, SYNTHETIC_VAL

import bakeoff_common as bakeoff  # noqa: E402  (path set up by dataset_common)
from evaluate import nfc, page_counts, rate, rates  # noqa: E402

DEFAULT_SPLITS = (REAL_VAL, SYNTHETIC_VAL, BAKEOFF_REGRESSION)
UNLOCK_LOG = "blind_test_unlocks.jsonl"
LOCKED = "LOCKED"


def unlock_log(root: Path) -> Path:
    return root / "manifests" / UNLOCK_LOG


def blind_test_unlocks(root: Path = dataset.DATASET_DIR) -> list[dict]:
    """Every time blind-test scores were computed; empty while nobody has looked."""
    path = unlock_log(root)
    return bakeoff.read_jsonl(path) if path.is_file() else []


def allowed_splits(requested: list[str], unlocked: bool) -> list[str]:
    if BLIND_TEST in requested and not unlocked:
        raise SystemExit(
            f"{BLIND_TEST} is locked. It is scored once, after a model and its settings are chosen, "
            "with --unlock-blind-test."
        )
    return requested


def score_rows(rows: list[dict], predictions: dict[str, str]) -> dict:
    """Micro-averaged rates of the rows that have a prediction."""
    scored = [row for row in rows if row["id"] in predictions]
    totals: dict[str, int] = {}
    exact = 0
    for row in scored:
        counts = page_counts(row["text"], predictions[row["id"]])
        for key, value in counts.items():
            totals[key] = totals.get(key, 0) + value
        exact += nfc(predictions[row["id"]]) == nfc(row["text"])
    result = {"lines": len(rows), "scored_lines": len(scored)}
    if scored:
        result.update(
            characters=totals["characters_gt"],
            words=totals["words_gt"],
            **rates(totals),
            exact_line_nfc=rate(exact, len(scored)),
        )
    return result


def score(splits: dict[str, list[dict]], predictions: dict[str, str], unlocked: bool) -> dict:
    """Metrics per set. The blind test is reported as locked unless ``unlocked``."""
    results = {}
    for split, rows in splits.items():
        if split == BLIND_TEST and not unlocked:
            waiting = sum(row["id"] in predictions for row in rows)
            results[split] = {"lines": len(rows), "status": LOCKED, "predictions_not_scored": waiting}
        elif any(row["id"] in predictions for row in rows):
            results[split] = score_rows(rows, predictions)
    return results


def record_unlock(root: Path, label: str, reason: str, who: str) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "label": label,
        "reason": reason,
        "by": who,
    }
    path = unlock_log(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + "\n")


def command_inputs(args: argparse.Namespace) -> int:
    splits = dataset.read_splits(args.root)
    rows = []
    for split in allowed_splits(args.splits, args.unlock_blind_test):
        for row in splits[split]:
            rows.append(
                {
                    "id": row["id"],
                    "split": split,
                    "crop_path": str((args.root / row["image_path"]).resolve()),
                    "crop_sha256": row["crop_sha256"],
                    "crop_width": int(row["image_width"] or 0),
                    "crop_height": int(row["image_height"] or 1),
                }
            )
    bakeoff.write_jsonl(args.output, rows)
    print(f"{len(rows)} crop(s) of {', '.join(args.splits)} -> {args.output}")
    return 0


def command_score(args: argparse.Namespace) -> int:
    predictions = {key: row["prediction"] for key, row in bakeoff.load_predictions(args.predictions).items()}
    splits = dataset.read_splits(args.root)
    if args.unlock_blind_test:
        if not args.reason:
            raise SystemExit("--unlock-blind-test needs --reason: say why the blind test is opened now.")
        # Written before anything is shown: a look that crashes still counts.
        record_unlock(args.root, args.label, args.reason, args.by or bakeoff_git_user())
    results = score(splits, predictions, args.unlock_blind_test)
    bakeoff.write_json(
        args.root / "manifests" / "evaluations" / f"{args.label}.json",
        {"label": args.label, "predictions": args.predictions.name, "results": results},
    )

    for split, result in results.items():
        if result.get("status") == LOCKED:
            print(f"{split}: LOCKED ({result['predictions_not_scored']} prediction(s) present, not scored)")
        elif result["scored_lines"]:
            print(
                f"{split}: {result['scored_lines']}/{result['lines']} lines | "
                f"CER raw={result['cer_raw']:.6f} nfc={result['cer_nfc']:.6f} | "
                f"WER raw={result['wer_raw']:.6f} nfc={result['wer_nfc']:.6f} | "
                f"exact line={result['exact_line_nfc']:.4f}"
            )
    if not any(result.get("scored_lines") for result in results.values()):
        print("no prediction matched a line of an unlocked set")
    return 0


def bakeoff_git_user() -> str:
    from annotate import git_user_name

    return git_user_name() or "unknown"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    inputs = commands.add_parser("inputs", help="List the crops to predict.")
    inputs.add_argument("--splits", nargs="+", default=list(DEFAULT_SPLITS), choices=dataset.SPLITS)
    inputs.add_argument("--output", type=Path, required=True)
    inputs.set_defaults(handler=command_inputs)

    scoring = commands.add_parser("score", help="Score predictions set by set.")
    scoring.add_argument("--predictions", type=Path, required=True)
    scoring.add_argument("--label", required=True, help="Name of the model or config being scored.")
    scoring.add_argument("--reason", default="", help="Why the blind test is unlocked (with --unlock-blind-test).")
    scoring.add_argument("--by", default="", help="Who unlocks it (default: git user.name).")
    scoring.set_defaults(handler=command_score)

    for command in (inputs, scoring):
        command.add_argument("--root", type=Path, default=dataset.DATASET_DIR)
        command.add_argument(
            "--unlock-blind-test",
            action="store_true",
            help="Include the blind test. Only once a model and its settings are final.",
        )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())

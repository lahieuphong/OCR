#!/usr/bin/env python3
"""Choose the final model from the evaluations of the fine-tuned candidates, by the agreed rule.

Usage:
    python datasets/vietnamese_recognition/select_model.py

Reads what ``evaluate_splits.py score`` wrote for each candidate and for the
pretrained baseline (``manifests/evaluations/<label>.json``) and applies, in
this order and with nothing else:

    1. the lowest CER (NFC) on real validation lines;
    2. on a tie, the lowest WER (NFC) on real validation lines;
    3. a sanity check on the bake-off regression lines: a candidate whose CER
       there is no higher than the baseline's passes; one that is higher is
       marked REVIEW with the size of the increase, for a person to judge.

A candidate is selected only if it reads real validation lines better than the
pretrained baseline. Otherwise the answer is that no fine-tuned model is to be
preferred.

The blind test takes no part. The selection refuses to run when an evaluation
holds blind-test scores or when the blind test has been unlocked: the model is
chosen first, and the blind test is opened afterwards, once.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import dataset_common as dataset
from dataset_common import BAKEOFF_REGRESSION, BLIND_TEST, REAL_VAL, SYNTHETIC_VAL

CANDIDATES = ("phase4_exp_a_width512", "phase4_exp_b_width1024")
BASELINE = "phase4_pretrained_w512"
LABEL_PREFIX = "phase4_"
REPORTED = ("cer_nfc", "wer_nfc", "exact_line_nfc", "decoder_limit_hits", "runtime_seconds")


def load(directory: Path, label: str) -> dict:
    path = directory / f"{label}.json"
    if not path.is_file():
        raise SystemExit(f"No evaluation named {label}: {path} does not exist.")
    evaluation = json.loads(path.read_text(encoding="utf-8"))
    blind = evaluation["results"].get(BLIND_TEST)
    if blind is not None and blind.get("status") != "LOCKED":
        raise SystemExit(f"STOP: {path.name} holds scores of the blind test. The model is selected without them.")
    for split in (REAL_VAL, BAKEOFF_REGRESSION):
        if "cer_nfc" not in evaluation["results"].get(split, {}):
            raise SystemExit(f"{path.name} has no result for {split}.")
    return evaluation


def key(evaluation: dict) -> tuple[float, float]:
    result = evaluation["results"][REAL_VAL]
    return result["cer_nfc"], result["wer_nfc"]


def choose(candidates: dict[str, dict], baseline: dict) -> dict:
    """The decision and everything it was taken on."""
    ranked = sorted(candidates, key=lambda label: (key(candidates[label]), label))
    best = ranked[0]
    reference = baseline["results"][BAKEOFF_REGRESSION]["cer_nfc"]
    table = {}
    for label in ranked:
        results = candidates[label]["results"]
        increase = results[BAKEOFF_REGRESSION]["cer_nfc"] - reference
        table[label] = {
            **{split: {name: results[split][name] for name in REPORTED if name in results[split]}
               for split in (REAL_VAL, SYNTHETIC_VAL, BAKEOFF_REGRESSION) if split in results},  # fmt: skip
            "better_than_baseline_on_real_val": key(candidates[label]) < key(baseline),
            "regression_cer_change": increase,
            "regression_sanity": "PASS" if increase <= 0 else "REVIEW",
        }
    improves = table[best]["better_than_baseline_on_real_val"]
    return {
        "rule": ["lowest real_val CER (NFC)", "then lowest real_val WER (NFC)", "regression sanity on bakeoff_regression"],
        "baseline": {split: {name: value for name, value in baseline["results"][split].items() if name in REPORTED}
                     for split in (REAL_VAL, SYNTHETIC_VAL, BAKEOFF_REGRESSION) if split in baseline["results"]},  # fmt: skip
        "candidates": table,
        "ranking": ranked,
        "selected": best if improves else None,
        "reason": (
            f"{best} has the lowest real_val CER/WER ({key(candidates[best])[0]:.6f} / {key(candidates[best])[1]:.6f}) and beats the "
            f"pretrained baseline ({key(baseline)[0]:.6f} / {key(baseline)[1]:.6f}); regression sanity: {table[best]['regression_sanity']}"
            if improves
            else f"no candidate reads real_val better than the pretrained baseline ({key(baseline)[0]:.6f} / {key(baseline)[1]:.6f})"
        ),
        "blind_test_used": False,
    }


def training_facts(label: str, repo: Path = dataset.REPO_ROOT) -> dict:
    """Where the weights came from and what the run needed, when its report is on this machine."""
    report = repo / "models" / "vietocr" / "finetuned" / label.removeprefix(LABEL_PREFIX) / "report.json"
    if not report.is_file():
        return {}
    record = json.loads(report.read_text(encoding="utf-8"))
    settings = record["settings"]
    return {
        "best_step": (record.get("best") or {}).get("step"),
        "steps_done": record.get("steps_done"),
        "physical_batch_size": settings.get("physical_batch_size"),
        "accumulation_steps": settings.get("accumulation_steps"),
        "batch_norm_statistics": settings.get("batch_norm_statistics"),
        "mixed_precision": settings.get("mixed_precision"),
        "memory": record.get("memory"),
        "gpu": record.get("environment", {}).get("gpu"),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--candidates", nargs="+", default=list(CANDIDATES), help="Labels given to evaluate_splits.py score.")
    parser.add_argument("--baseline", default=BASELINE)
    parser.add_argument("--evaluations-dir", type=Path, default=dataset.MANIFESTS_DIR / "evaluations")
    parser.add_argument("--root", type=Path, default=dataset.DATASET_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from evaluate_splits import blind_test_unlocks

    args = parse_args(argv)
    if blind_test_unlocks(args.root):
        raise SystemExit("STOP: the blind test has been unlocked. A model is selected before that, not after.")
    baseline = load(args.evaluations_dir, args.baseline)
    candidates = {label: load(args.evaluations_dir, label) for label in args.candidates}
    decision = choose(candidates, baseline)
    for label in decision["candidates"]:
        decision["candidates"][label]["training"] = training_facts(label)
    dataset.write_text_atomic(args.evaluations_dir / "phase4_selection.json", json.dumps(decision, ensure_ascii=False, indent=2) + "\n")

    def line(name: str, results: dict) -> str:
        cells = []
        for split in (REAL_VAL, SYNTHETIC_VAL, BAKEOFF_REGRESSION):
            if split in results:
                r = results[split]
                cells.append(f"{split} CER {r['cer_nfc']:.6f} WER {r['wer_nfc']:.6f} exact {r['exact_line_nfc']:.4f} hits {r.get('decoder_limit_hits', '-')}")
        return f"{name}: " + " | ".join(cells)

    print(line(f"baseline {args.baseline}", decision["baseline"]))
    for label in decision["ranking"]:
        entry = decision["candidates"][label]
        print(line(label, entry) + f" | regression sanity {entry['regression_sanity']} ({entry['regression_cer_change']:+.6f})")
    print(f"SELECTED: {decision['selected'] or 'none'}")
    print(f"reason: {decision['reason']}")
    print("blind test: not used, still locked")
    return 0


if __name__ == "__main__":
    sys.exit(main())

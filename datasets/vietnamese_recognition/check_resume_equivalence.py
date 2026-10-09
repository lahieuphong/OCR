#!/usr/bin/env python3
"""Check that a run stopped and resumed ends exactly where an uninterrupted run ends.

Usage (on the machine that will train, VietOCR environment):
    python datasets/vietnamese_recognition/check_resume_equivalence.py \\
        --config configs/vietnamese/vietocr/exp_a_width512.yml \\
        --batch-size 16 --accumulation-steps 1

A gate before the full runs. With the settings of the real run (seed, batch,
schedule, batch-norm policy, device) it starts three processes:

    1. 40 optimizer steps without interruption;
    2. the first 20 steps of the same run, which saves its checkpoint and ends;
    3. a new process that resumes that checkpoint and runs steps 21 to 40.

It then compares, at step 40, the weights and buffers of the network, the
state of the optimizer, the state of the scheduler and its learning rate, the
number of steps done, and the loss of each of the steps 21 to 40.

The verdict is PASS only if all of it is identical. Where something differs,
the largest absolute difference is reported; ``--tolerance`` accepts
differences up to a stated size, which is a decision to take with the numbers
in hand, not a default. On FAIL the exit status is 1: do not start a full run
that may have to be resumed.

The checkpoints are deleted afterwards (about 1.5 GB); the reports stay, and
the verdict is written to ``resume_gate.json`` next to them.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

import dataset_common as dataset

TRAINER = dataset.DATASET_DIR / "train_vietocr.py"
CONTINUOUS, RESUMED = "resume_gate_continuous", "resume_gate_resumed"
STEPS = 40


def commands(config: Path, steps: int, extra: list[str]) -> list[list[str]]:
    """The three processes of the gate, in order."""
    base = [sys.executable, str(TRAINER), "--config", str(config), "--smoke", "--diagnostic-lines", "0", *extra]
    return [
        [*base, "--run-name", CONTINUOUS, "--steps", str(steps), "--overwrite"],
        [*base, "--run-name", RESUMED, "--steps", str(steps // 2), "--overwrite"],
        [*base, "--run-name", RESUMED, "--steps", str(steps), "--resume"],
    ]


def largest_difference(first, second) -> float:
    """0.0 when two values are identical; otherwise the largest absolute difference, or infinity when they cannot be compared."""
    import torch

    if isinstance(first, torch.Tensor) and isinstance(second, torch.Tensor):
        if first.shape != second.shape or first.dtype != second.dtype:
            return float("inf")
        if torch.equal(first, second):
            return 0.0
        return float((first.double() - second.double()).abs().max()) if first.numel() else 0.0
    if isinstance(first, dict) and isinstance(second, dict):
        if first.keys() != second.keys():
            return float("inf")
        return max((largest_difference(first[key], second[key]) for key in first), default=0.0)
    if isinstance(first, (list, tuple)) and isinstance(second, (list, tuple)):
        if len(first) != len(second):
            return float("inf")
        return max((largest_difference(a, b) for a, b in zip(first, second)), default=0.0)
    if isinstance(first, bool) or isinstance(second, bool) or first is None or second is None:
        return 0.0 if first == second else float("inf")
    if isinstance(first, (int, float)) and isinstance(second, (int, float)):
        return abs(float(first) - float(second))
    return 0.0 if first == second else float("inf")


def compare(continuous: dict, resumed: dict, steps: int, tolerance: float = 0.0) -> dict:
    """Both training states at the last step, part by part."""
    half = steps // 2
    parts = {
        "model_state_dict": (continuous["model"], resumed["model"]),
        "optimizer_state": (continuous["optimizer"], resumed["optimizer"]),
        "scheduler_state": (continuous["scheduler"], resumed["scheduler"]),
        "learning_rate": (continuous["scheduler"]["_last_lr"], resumed["scheduler"]["_last_lr"]),
        "optimizer_steps": (continuous["step"], resumed["step"]),
        f"losses_of_steps_{half + 1}_to_{steps}": (continuous["record"]["step_losses"][half:steps], resumed["record"]["step_losses"][half:steps]),
        "losses_of_all_steps": (continuous["record"]["step_losses"], resumed["record"]["step_losses"]),
        "random_state": (continuous["torch_rng"], resumed["torch_rng"]),
    }
    report = {}
    for name, (first, second) in parts.items():
        difference = largest_difference(first, second)
        report[name] = {"identical": difference == 0.0, "largest_absolute_difference": difference}
    complete = continuous["step"] == resumed["step"] == steps and len(resumed["record"]["step_losses"]) == steps
    identical = complete and all(entry["identical"] for entry in report.values())
    within = complete and all(entry["largest_absolute_difference"] <= tolerance for entry in report.values())
    return {
        "steps": steps,
        "resumed_at": half,
        "both_runs_reached_the_last_step": complete,
        "parts": report,
        "identical": identical,
        "tolerance": tolerance,
        "result": "PASS" if identical or (tolerance > 0 and within) else "FAIL",
    }


def parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=STEPS, help="Optimizer steps of the uninterrupted run; the other stops at half.")
    parser.add_argument("--tolerance", type=float, default=0.0, help="Largest absolute difference accepted (default: none).")
    parser.add_argument("--keep-files", action="store_true", help="Do not delete the checkpoints afterwards.")
    return parser.parse_known_args(argv)  # the rest goes to train_vietocr.py (--batch-size, --device, --amp ...)


def main(argv: list[str] | None = None) -> int:
    args, extra = parse_args(argv)
    if args.steps < 2 or args.steps % 2:
        raise SystemExit("--steps must be an even number.")
    import torch

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    directory = (dataset.REPO_ROOT / config["trainer"]["export"]).parent
    for command in commands(args.config.resolve(), args.steps, extra):
        completed = subprocess.run(command, cwd=dataset.REPO_ROOT, check=False)
        if completed.returncode != 0:
            raise SystemExit(f"STOP: a run of the gate ended with status {completed.returncode}: {' '.join(command[1:])}")
    states = {name: torch.load(directory / name / "checkpoint.pth", map_location="cpu", weights_only=False) for name in (CONTINUOUS, RESUMED)}
    verdict = compare(states[CONTINUOUS], states[RESUMED], args.steps, args.tolerance)
    verdict["settings"] = states[CONTINUOUS]["record"]["settings"]
    verdict["environment"] = states[RESUMED]["record"].get("environment", {})
    dataset.write_text_atomic(directory / "resume_gate.json", json.dumps(verdict, ensure_ascii=False, indent=2) + "\n")
    if not args.keep_files:
        for name in (CONTINUOUS, RESUMED):
            for file in (directory / name).glob("*.pth"):
                file.unlink()

    for name, entry in verdict["parts"].items():
        note = "identical" if entry["identical"] else f"DIFFERS, largest absolute difference {entry['largest_absolute_difference']:.3e}"
        print(f"  {name}: {note}")
    print(f"RESUME GATE: {verdict['result']} ({args.steps} steps, resumed at {args.steps // 2}) -> {directory / 'resume_gate.json'}")
    if verdict["result"] != "PASS":
        print("STOP: do not start a full run that may have to be resumed.")
    return 0 if verdict["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

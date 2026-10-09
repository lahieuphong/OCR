#!/usr/bin/env python3
"""Find the largest batch that fits the GPU for the widest experiment, to be used by both.

Usage (on the machine with the GPU, VietOCR environment):
    python datasets/vietnamese_recognition/probe_cuda_batch.py

Tries, for the 1024-pixel experiment and in this order,

    16 lines per forward pass, no accumulation
     8 lines per forward pass, gradients of 2 passes per step
     4 lines per forward pass, gradients of 4 passes per step

each in a process of its own (``train_vietocr.py --probe-memory``), on the most
demanding batches of the training data, and stops at the first that does not
run out of memory. The effective batch is 16 in every case.

Both experiments then have to run with that batch size and that number of
accumulation steps, the 512-pixel one too although it would fit more: the
experiments may differ in width only. The result, with the GPU, its memory,
the versions and the peak memory of every attempt, is written to
``models/vietocr/finetuned/batch_probe.json``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import dataset_common as dataset
from build_vietocr_config import EFFECTIVE_BATCH_SIZE, config_path

TRAINER = dataset.DATASET_DIR / "train_vietocr.py"
WIDEST_EXPERIMENT = "exp_b_width1024"
# (lines per forward pass, forward passes per optimizer step), largest first.
CANDIDATES = ((16, 1), (8, 2), (4, 4))
OUT_OF_MEMORY_STATUS = 3
RESULT = dataset.REPO_ROOT / "models" / "vietocr" / "finetuned" / "batch_probe.json"


def probe_command(config: Path, batch_size: int, accumulation: int, extra: list[str]) -> list[str]:
    return [sys.executable, str(TRAINER), "--config", str(config), "--probe-memory",
            "--batch-size", str(batch_size), "--accumulation-steps", str(accumulation), *extra]  # fmt: skip


def choose(attempts: list[dict]) -> dict | None:
    """The first attempt, in the order tried, that ran its steps without running out of memory."""
    return next((attempt for attempt in attempts if not attempt["out_of_memory"] and attempt.get("loss_finite")), None)


def flags(selected: dict) -> str:
    return f"--batch-size {selected['physical_batch_size']} --accumulation-steps {selected['accumulation_steps']}"


def parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=config_path(WIDEST_EXPERIMENT), help="Default: the widest experiment.")
    parser.add_argument("--output", type=Path, default=RESULT)
    return parser.parse_known_args(argv)  # the rest goes to train_vietocr.py (--device, --amp ...)


def main(argv: list[str] | None = None) -> int:
    args, extra = parse_args(argv)
    if any(batch * accumulation != EFFECTIVE_BATCH_SIZE for batch, accumulation in CANDIDATES):
        raise SystemExit("Every candidate must keep the effective batch of the experiments.")
    attempts = []
    for batch_size, accumulation in CANDIDATES:
        completed = subprocess.run(probe_command(args.config, batch_size, accumulation, extra), cwd=dataset.REPO_ROOT, check=False)
        report = (dataset.REPO_ROOT / "models" / "vietocr" / "finetuned" / args.config.stem / "probe"
                  / f"probe_batch{batch_size}x{accumulation}.json")  # fmt: skip
        if completed.returncode not in (0, OUT_OF_MEMORY_STATUS) or not report.is_file():
            raise SystemExit(f"The probe of batch {batch_size} x {accumulation} failed for another reason than memory (status {completed.returncode}).")
        attempts.append(json.loads(report.read_text(encoding="utf-8")))
        if choose(attempts):
            break
    selected = choose(attempts)
    result = {
        "experiment_probed": args.config.stem,
        "attempts": attempts,
        "selected": {key: selected[key] for key in ("physical_batch_size", "accumulation_steps", "effective_batch_size")} if selected else None,
        "use_for_both_experiments": flags(selected) if selected else None,
    }
    dataset.write_text_atomic(args.output, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    if not selected:
        print("No candidate fits this device: not even 4 lines per forward pass. Do not train here.")
        return 1
    print(f"Largest batch that fits {args.config.stem}: {selected['physical_batch_size']} x {selected['accumulation_steps']}.")
    print(f"Run BOTH experiments with: {flags(selected)}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

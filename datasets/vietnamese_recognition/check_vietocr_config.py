#!/usr/bin/env python3
"""Check that the fine-tuning configs are ready to train from, without training.

Usage (VietOCR environment, ``.venv-vietocr``):
    python datasets/vietnamese_recognition/check_vietocr_config.py

For each config of the width experiment, does what a training run would do
before its first step, then stops:

    1. builds the model from the config and loads the pretrained checkpoint
       the way ``vietocr.model.trainer.Trainer.load_weights`` does, reporting
       any tensor that would not load;
    2. encodes every training and validation label with the model's
       vocabulary, checks its image exists, and refuses a config whose
       training or validation file holds a line of the blind test or of the
       bake-off regression, or whose validation file is not real lines only;
    3. runs one forward pass, without gradients, at the pretrained width and
       at the configured maximum width, and measures the activations.

From those measurements it estimates the memory and time of a training step,
on this machine and for a given batch size. The estimate is an extrapolation
from a forward pass, not a measurement of training: no optimizer is created
and no weight is changed.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import dataset_common as dataset
from build_vietocr_config import supported_label_characters

from run_vietocr import VIETOCR_COMMIT, check_pinned_checkout  # noqa: E402  (path set up by dataset_common)

CONFIGS = sorted(dataset.VIETOCR_CONFIG_DIR.glob("exp_*.yml"))
BYTES_PER_FLOAT = 4
# A training step keeps the activations for the backward pass and computes a
# gradient of each: about twice the forward activations. AdamW holds the
# weights, their gradients and two moment estimates.
ACTIVATION_FACTOR = 2.0
PARAMETER_COPIES = 4
STEP_TO_FORWARD_TIME = 3.0


def megabytes(count: float) -> float:
    return count * BYTES_PER_FLOAT / 1024**2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, action="append", help="Default: every exp_*.yml.")
    parser.add_argument("--device", default="cpu", choices=("cpu", "mps"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    check_pinned_checkout()
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(dataset.VIETOCR_DIR))
    ready = [check(path, args.device) for path in (args.config or CONFIGS)]
    return 0 if ready and all(ready) else 1


def check(path: Path, device: str) -> bool:
    """Everything short of a training step for one config; True when it could start."""
    import argparse as _argparse

    args = _argparse.Namespace(config=path, device=device)
    import torch
    from vietocr.tool.config import Cfg
    from vietocr.tool.translate import build_model

    config = Cfg.load_config_from_file(str(args.config))
    config["device"] = args.device  # the file says cuda; this check runs wherever it is started
    root = dataset.REPO_ROOT
    print(f"config: {args.config.relative_to(root)} (VietOCR {VIETOCR_COMMIT[:10]})")

    # 1. model and pretrained weights
    model, vocab = build_model(config)
    state = torch.load(root / config["pretrain"], map_location=torch.device(args.device))
    parameters = dict(model.named_parameters())
    not_found = [name for name in parameters if name not in state]
    mismatched = [name for name, value in parameters.items() if name in state and state[name].shape != value.shape]
    model.load_state_dict({k: v for k, v in state.items() if k not in mismatched}, strict=False)
    total = sum(value.numel() for value in parameters.values())
    print(f"1. model: {total:,} parameters; vocabulary: {len(vocab)} classes")
    print(f"   pretrained tensors not found: {len(not_found)}, with another shape: {len(mismatched)}")

    # 2. annotations
    data_root = root / config["dataset"]["data_root"]
    problems, longest = [], 0
    counts = {}
    for key in ("train_annotation", "valid_annotation"):
        path = data_root / config["dataset"][key]
        lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
        counts[key] = len(lines)
        if not lines:
            problems.append(f"{path.name}: no line in this set yet")
        for line in lines:
            fields = line.strip().split("\t")  # as vietocr.tool.create_dataset reads it
            if len(fields) != 2:
                problems.append(f"{key}: not two fields: {line[:40]!r}")
                continue
            image, label = fields
            longest = max(longest, len(label))
            try:
                vocab.encode(label)
            except KeyError as error:
                problems.append(f"{image}: character {error} is not in the vocabulary")
            if not (data_root / image).is_file():
                problems.append(f"{image}: image not found")
    # Training reads the training sets, validation reads real lines, and
    # neither ever reads the blind test or the bake-off regression.
    problems += dataset.training_data_problems(
        data_root / config["dataset"]["train_annotation"], data_root / config["dataset"]["valid_annotation"], data_root
    )
    limit = supported_label_characters(config)
    if longest > limit:
        problems.append(f"longest label has {longest} characters; this config supports {limit} "
                        f"(decoder_max_seq_length {config['decoder_max_seq_length']})")
    print(f"2. annotations: {counts['train_annotation']} training and {counts['valid_annotation']} validation lines; "
          f"longest label {longest} characters (supported: {limit}); problems: {len(problems)}")
    for problem in problems[:10]:
        print(f"   {problem}")

    # 3. one forward pass per width, no gradients
    sizes: list[int] = []

    def record(_module, _inputs, output) -> None:
        if isinstance(output, torch.Tensor):
            sizes.append(output.numel())

    hooks = [module.register_forward_hook(record) for module in model.modules() if not list(module.children())]
    model.eval()
    height = config["dataset"]["image_height"]
    batch = config["trainer"]["batch_size"]
    print("3. forward pass of one image, without gradients")
    measured = {}
    for width in sorted({512, config["dataset"]["image_max_width"]}):
        sizes.clear()
        image = torch.rand(1, 3, height, width, device=args.device)
        # A 100-character label, time first, as the collator hands it to the model.
        target = torch.ones(100, 1, dtype=torch.long, device=args.device)
        padding = torch.zeros(1, 100, dtype=torch.bool, device=args.device)  # nothing is padding
        with torch.no_grad():
            started = time.perf_counter()
            output = model(image, target, tgt_key_padding_mask=padding)
            seconds = time.perf_counter() - started
        measured[width] = (megabytes(sum(sizes)), seconds)
        print(f"   width {width}: activations {measured[width][0]:.0f} MB, output {tuple(output.shape)}, "
              f"{seconds:.2f} s on {args.device}")
    for hook in hooks:
        hook.remove()

    weights = megabytes(total) * PARAMETER_COPIES
    print("estimate of one training step (extrapolated, not measured):")
    for width, (activations, seconds) in measured.items():
        for size in sorted({1, 2, 4, batch}):
            memory = weights + activations * ACTIVATION_FACTOR * size
            print(f"   width {width}, batch {size:2d}: about {memory / 1024:.1f} GB, "
                  f"about {seconds * STEP_TO_FORWARD_TIME * size:.1f} s per step on this {args.device}")
    ready = not problems and not not_found and not mismatched
    print(f"READY TO TRAIN FROM: {'yes' if ready else 'NO'} (nothing was trained)")
    return ready


if __name__ == "__main__":
    sys.exit(main())

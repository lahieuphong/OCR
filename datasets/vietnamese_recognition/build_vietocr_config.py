#!/usr/bin/env python3
"""Write the VietOCR fine-tuning configs of the width experiment.

Usage:
    python datasets/vietnamese_recognition/build_vietocr_config.py            # write them
    python datasets/vietnamese_recognition/build_vietocr_config.py --check    # verify them

Two configs are written, for two training runs that differ in one thing only,
the widest image the recognizer is given:

    exp_a_width512.yml    image_max_width = 512   (the pretrained value)
    exp_b_width1024.yml   image_max_width = 1024

Dataset, training mix, seed, pretrained checkpoint, learning rate, batch size
and number of iterations are the same in both; only the width and the place
each run writes its outputs differ. Which width wins is decided on real
validation lines, never on the blind test.

The number of optimizer steps is not a constant: it is derived from the size
of one training pass, as ``build_dataset.py`` recorded it in
``manifests/build_report.json``. When the training mix changes, ``--check``
reports the configs as out of date.

Each config is the pretrained ``vgg_transformer`` configuration of the pinned
VietOCR checkout (``config/base.yml`` merged with ``config/vgg-transformer.yml``,
the way ``Cfg.load_config_from_name`` merges them) with the overrides listed in
``OVERRIDES`` below. Nothing in ``third_party/vietocr`` is edited.

The vocabulary is deliberately left as it is. It already holds every
Vietnamese letter, and changing it would change the size of the output layer,
which could then no longer be loaded from the pretrained checkpoint.

This script prepares files. It does not train anything.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path

import yaml

import dataset_common as dataset

BASE_FILES = ("base.yml", "vgg-transformer.yml")
DATASET_NAME = "vi_admin_pilot_v1"
OUTPUT_DIR = "models/vietocr/finetuned"
# The one setting the two experiments differ in.
EXPERIMENTS = {"exp_a_width512": 512, "exp_b_width1024": 1024}
# Samples behind one optimizer step: the batch size times the accumulation steps.
EFFECTIVE_BATCH_SIZE = 16
# Passes over the training mix. A first, conservative budget: every real line is
# already repeated within a pass, and the weights kept are the best on real
# validation lines, not the last ones.
EPOCHS = 10
VALIDATIONS_PER_EPOCH = 2


def schedule() -> dict:
    """Optimizer steps of a run, from the training pass the dataset build recorded."""
    report = json.loads((dataset.MANIFESTS_DIR / "build_report.json").read_text(encoding="utf-8"))
    samples = report["training_mix"]["samples_per_pass"]
    steps_per_epoch = math.ceil(samples / EFFECTIVE_BATCH_SIZE)
    return {
        "samples_per_pass": samples,
        "effective_batch_size": EFFECTIVE_BATCH_SIZE,
        "steps_per_epoch": steps_per_epoch,
        "epochs": EPOCHS,
        "total_steps": EPOCHS * steps_per_epoch,
        "validate_every": steps_per_epoch // VALIDATIONS_PER_EPOCH,
    }


SCHEDULE = schedule()

# Paths are relative to the repository root, where training is started from.
OVERRIDES = {
    # The checkpoint the bake-off evaluated, as a local file instead of a URL.
    "pretrain": "models/vietocr/vgg_transformer.pth",
    "device": "cuda:0",
    # ImageNet weights would be downloaded only to be overwritten by `pretrain`.
    "cnn": {"pretrained": False},
    "dataset": {
        # Both experiments share this name, hence the same cached training data.
        "name": DATASET_NAME,
        "data_root": "datasets/vietnamese_recognition",
        # Real and synthetic lines mixed as data_mix.yml says.
        "train_annotation": "manifests/vietocr/train_mix_annotation.txt",
        # Real lines only: VietOCR keeps the weights that do best on this file.
        "valid_annotation": "manifests/vietocr/real_val_annotation.txt",
        "image_height": 32,
        "image_min_width": 32,
    },
    "trainer": {
        # Lines per forward pass. With `experiment.accumulation_steps` it makes
        # the effective batch; a machine short of memory lowers this and raises
        # the other, in both experiments alike.
        "batch_size": EFFECTIVE_BATCH_SIZE,
        "print_every": 50,
        # Optimizer steps, from `schedule()`: see `experiment.schedule`.
        "valid_every": SCHEDULE["validate_every"],
        "iters": SCHEDULE["total_steps"],
        # Read by VietOCR's own trainer only, which these runs do not use.
        "metrics": 10000,
    },
    # A third of the pretrained peak rate: adapt the model, do not retrain it.
    "optimizer": {"max_lr": 0.0001, "pct_start": 0.1},
    "aug": {
        # The dataset is already degraded, reproducibly. VietOCR's own transform
        # would also invert a fifth of the images and draw coloured lines.
        "image_aug": False,
        "masked_language_model": True,
    },
    "dataloader": {"num_workers": 4, "pin_memory": True},
    "predictor": {"beamsearch": False},
    # Not read by VietOCR. Decoding steps the project's own runner allows
    # (run_vietocr.py --config). 128 is also what VietOCR's `translate` does
    # when left alone, but here it is a setting, stated and passed explicitly.
    # No verified real label is longer than 92 characters and no synthetic one
    # longer than 119; with 128 and with 160 steps the pretrained model read
    # every line that ends by itself identically, and more steps only made a
    # line it never ends longer. Raise it when a real label needs it.
    "decoder_max_seq_length": 128,
    # Not read by VietOCR: how the run is to be seeded, judged and compared.
    # train_vietocr.py reads this block.
    "experiment": {
        "seed": 20261201,
        # Forward passes whose gradients are summed before one optimizer step.
        "accumulation_steps": 1,
        # The batch-norm layers of the backbone keep the running mean and
        # variance of the pretrained checkpoint: they normalise with them and do
        # not re-estimate them from the training batches. Their scale and shift
        # (gamma, beta) are trained like every other weight, and nothing else in
        # the backbone is frozen. The pinned trainer would update the statistics
        # ("updated"); with few lines per forward pass that alone cost a third
        # of the line accuracy within 20 steps.
        "batch_norm_statistics": "frozen",
        "schedule": SCHEDULE,
        "data_mix": "configs/vietnamese/vietocr/data_mix.yml",
        "selection_split": dataset.REAL_VAL,
        "selection_metric": "cer_nfc",
        "selection_tiebreak": "wer_nfc",
        "diagnostic_splits": [dataset.SYNTHETIC_VAL, dataset.BAKEOFF_REGRESSION],
        # Scored once, after a config is chosen, with --unlock-blind-test.
        "blind_split": dataset.BLIND_TEST,
        "blind_test_used_for_selection": False,
    },
}

HEADER = """\
# VietOCR fine-tuning config: Vietnamese administrative documents, width experiment.
#
# GENERATED by datasets/vietnamese_recognition/build_vietocr_config.py from the
# pinned checkout third_party/vietocr (config/base.yml + config/vgg-transformer.yml).
# Change the overrides in that script, not this file; `--check` compares them.
# The two experiment files must differ in image_max_width and output paths only.
#
# Nothing has been trained with this file. See README.md in this directory.
"""


def config_path(name: str) -> Path:
    return dataset.VIETOCR_CONFIG_DIR / f"{name}.yml"


def experiment_overrides(name: str) -> dict:
    """What one experiment sets on top of the shared overrides."""
    folder = f"{OUTPUT_DIR}/{name}"
    return {
        # Where a predictor finds the fine-tuned weights afterwards.
        "weights": f"{folder}/weights.pth",
        "dataset": {"image_max_width": EXPERIMENTS[name]},
        "trainer": {
            "export": f"{folder}/weights.pth",
            "checkpoint": f"{folder}/checkpoint.pth",
            "log": f"{folder}/train.log",
        },
        "experiment": {"name": name},
    }


def deep_update(target: dict, changes: dict) -> dict:
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_update(target[key], value)
        else:
            target[key] = copy.deepcopy(value)
    return target


def pretrained_config() -> dict:
    """The stock ``vgg_transformer`` config of the pinned checkout."""
    merged: dict = {}
    for name in BASE_FILES:
        with (dataset.VIETOCR_DIR / "config" / name).open(encoding="utf-8") as stream:
            merged.update(yaml.safe_load(stream))
    return merged


def fine_tuning_config(name: str) -> dict:
    return deep_update(deep_update(pretrained_config(), OVERRIDES), experiment_overrides(name))


def supported_label_characters(config: dict) -> int:
    """Longest label a run from this config can be trained on and can read back whole.

    Two capacities bound it:

        decoder       ``translate`` writes at most ``decoder_max_seq_length + 1``
                      tokens, and the last one has to be the end token;
        transformer   it has ``transformer.max_seq_length`` positions, and a
                      training target is the label between a start and an end
                      token.

    VietOCR has no shorter limit of its own: ``Vocab.encode`` and the training
    collator take a label of any length.
    """
    return min(config["decoder_max_seq_length"], config["transformer"]["max_seq_length"] - 2)


def label_limit() -> dict:
    """The label length the experiment configs on disk support, and what sets it.

    With several configs the shortest limit counts: a line is usable only if
    every experiment can train on it and read it.
    """
    limits = []
    for name in EXPERIMENTS:
        path = config_path(name)
        if not path.is_file():
            raise SystemExit(f"{path} does not exist: run build_vietocr_config.py.")
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        if "decoder_max_seq_length" not in config:
            raise SystemExit(f"{path} sets no decoder_max_seq_length: run build_vietocr_config.py.")
        limits.append(
            {
                "characters": supported_label_characters(config),
                "decoder_max_seq_length": config["decoder_max_seq_length"],
                "transformer_max_seq_length": config["transformer"]["max_seq_length"],
                "config": path.name,
            }
        )
    return min(limits, key=lambda limit: limit["characters"])


def render_config(name: str) -> str:
    body = yaml.safe_dump(fine_tuning_config(name), allow_unicode=True, sort_keys=False, width=1000)
    return HEADER + body


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="Write nothing; fail if a file is out of date.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    status = 0
    for name in EXPERIMENTS:
        text, path = render_config(name), config_path(name)
        if yaml.safe_load(text) != fine_tuning_config(name):
            raise SystemExit(f"{name}: the config does not survive a YAML round trip.")
        if args.check:
            current = path.is_file() and path.read_text(encoding="utf-8") == text
            print(f"{'up to date' if current else 'OUT OF DATE'}: {path}")
            status |= not current
        else:
            dataset.write_text_atomic(path, text)
            print(f"wrote {path}")
    return status


if __name__ == "__main__":
    sys.exit(main())

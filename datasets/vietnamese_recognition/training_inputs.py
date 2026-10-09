#!/usr/bin/env python3
"""Record the exact inputs of the fine-tuning experiments, and check them later.

Usage:
    python datasets/vietnamese_recognition/training_inputs.py            # freeze
    python datasets/vietnamese_recognition/training_inputs.py --check    # verify

Writes ``manifests/training_inputs.json`` with the SHA-256 of

    the four manifests a run learns from or is selected on
        real_train.tsv, real_val.tsv, synthetic_train.tsv, synthetic_val.tsv
    the two files a run actually reads
        manifests/vietocr/train_mix_annotation.txt   (training)
        manifests/vietocr/real_val_annotation.txt    (validation)
    both experiment configs and the mixing rule
    the pretrained checkpoint every run starts from

``train_vietocr.py`` recomputes these before a run and refuses to start when
one differs from the record, and it copies them into the report of the run.
Two experiments are comparable only if they read the same data: a run whose
data digests differ from those of the other experiment's report stops too.

The record says what the inputs were. It does not protect the files: after a
deliberate change of the dataset or of a config, freeze again with ``--force``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import dataset_common as dataset

LOCK = dataset.MANIFESTS_DIR / "training_inputs.json"
# Name -> path below the dataset directory.
DATASET_FILES = {
    "real_train": "manifests/real_train.tsv",
    "real_val": "manifests/real_val.tsv",
    "synthetic_train": "manifests/synthetic_train.tsv",
    "synthetic_val": "manifests/synthetic_val.tsv",
    "train_mix_annotation": "manifests/vietocr/train_mix_annotation.txt",
    "real_val_annotation": "manifests/vietocr/real_val_annotation.txt",
}
CONFIG_FILES = ("exp_a_width512.yml", "exp_b_width1024.yml", "data_mix.yml")
PRETRAINED = "models/vietocr/vgg_transformer.pth"
# The parts every experiment must share.
SHARED = ("dataset", "pretrained")


def describe(path: Path, relative_to: Path) -> dict:
    if not path.is_file():
        raise SystemExit(f"Missing training input: {path}")
    entry = {"path": path.relative_to(relative_to).as_posix(), "sha256": dataset.sha256_file(path)}
    if path.suffix in (".tsv", ".txt"):
        with path.open("rb") as stream:
            entry["lines"] = sum(1 for _ in stream)
    return entry


def current(root: Path = dataset.DATASET_DIR, repo: Path = dataset.REPO_ROOT) -> dict:
    """The digests of the inputs as they are on disk now."""
    return {
        "dataset": {name: describe(root / relative, root) for name, relative in DATASET_FILES.items()},
        "configs": {name: describe(repo / "configs" / "vietnamese" / "vietocr" / name, repo) for name in CONFIG_FILES},
        "pretrained": describe(repo / PRETRAINED, repo),
    }


def load(path: Path = LOCK) -> dict:
    if not path.is_file():
        raise SystemExit(f"No frozen training inputs at {path}: run training_inputs.py first.")
    return json.loads(path.read_text(encoding="utf-8"))


def flatten(digests: dict, parts: tuple[str, ...] | None = None) -> dict[str, str]:
    """``part/name`` -> SHA-256 for the parts asked for (all of them by default)."""
    flat = {}
    for part in parts or ("dataset", "configs", "pretrained"):
        value = digests[part]
        if "sha256" in value:
            flat[part] = value["sha256"]
        else:
            flat.update({f"{part}/{name}": entry["sha256"] for name, entry in value.items()})
    return flat


def differences(recorded: dict, found: dict, parts: tuple[str, ...] | None = None) -> list[str]:
    """What differs between two sets of digests, one line per input."""
    before, after = flatten(recorded, parts), flatten(found, parts)
    return [
        f"{name}: recorded {before.get(name, 'nothing')[:16]}, found {after.get(name, 'nothing')[:16]}"
        for name in sorted(before.keys() | after.keys())
        if before.get(name) != after.get(name)
    ]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="Write nothing; fail if an input differs from the record.")
    parser.add_argument("--force", action="store_true", help="Replace an existing record that differs.")
    parser.add_argument("--lock", type=Path, default=LOCK)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    found = current()
    if args.check:
        changed = differences(load(args.lock), found)
        for line in changed:
            print(f"CHANGED {line}")
        print(f"training inputs: {'DIFFER from' if changed else 'match'} {args.lock.name}")
        return 1 if changed else 0

    if args.lock.is_file():
        changed = differences(load(args.lock), found)
        if not changed:
            print(f"training inputs already frozen and unchanged: {args.lock}")
            return 0
        if not args.force:
            raise SystemExit("The frozen training inputs differ from the files on disk:\n  " + "\n  ".join(changed)
                             + "\nUse --force to freeze the files as they are now.")  # fmt: skip
    dataset.write_text_atomic(
        args.lock,
        json.dumps({"frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **found}, ensure_ascii=False, indent=2) + "\n",
    )
    for name, digest in flatten(found).items():
        print(f"{digest}  {name}")
    print(f"wrote {args.lock}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

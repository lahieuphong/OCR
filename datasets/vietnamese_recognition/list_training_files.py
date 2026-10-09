#!/usr/bin/env python3
"""List every file a fine-tuning run and its evaluation read that git does not hold.

Usage:
    python datasets/vietnamese_recognition/list_training_files.py > training_files.txt
    tar czf ocr_training_data.tgz -T training_files.txt        # then unpack at the root of the clone

For moving the work to a machine with a GPU. The clone brings code, configs
and manifests; this list is the rest:

    the images of real_train, real_val, synthetic_train, synthetic_val
    the images of bakeoff_regression (evaluation after training)
    the VietOCR annotation files of the training and validation sets
    the pretrained checkpoint

No image of the blind test is listed: it is not needed to train or to select a
model, so it does not have to leave this machine. Paths are relative to the
repository root. A file that is missing here is an error, not a gap in the list.
"""

from __future__ import annotations

import sys
from pathlib import Path

import dataset_common as dataset
import training_inputs
from dataset_common import BAKEOFF_REGRESSION, LEARNING_SPLITS

# Sets whose images a run or its evaluation opens. The blind test is not one of them.
IMAGE_SPLITS = LEARNING_SPLITS + (BAKEOFF_REGRESSION,)


def training_files(root: Path = dataset.DATASET_DIR, repo: Path = dataset.REPO_ROOT) -> list[Path]:
    files = {repo / training_inputs.PRETRAINED}
    files |= {path for path in (root / "manifests" / "vietocr").glob("*_annotation.txt")}
    for split in IMAGE_SPLITS:
        for row in dataset.read_manifest(dataset.manifest_path(split, root)):
            files.add((root / row["image_path"]).resolve())
    return sorted(files)


def main() -> int:
    missing = 0
    for path in training_files():
        if not path.is_file():
            print(f"MISSING {path}", file=sys.stderr)
            missing += 1
            continue
        print(path.relative_to(dataset.REPO_ROOT.resolve()).as_posix())
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())

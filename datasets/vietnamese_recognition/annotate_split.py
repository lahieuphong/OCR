#!/usr/bin/env python3
"""Verify the ground truth of one set of the new real documents.

Usage:
    python datasets/vietnamese_recognition/annotate_split.py real_train
    python datasets/vietnamese_recognition/annotate_split.py real_val
    python datasets/vietnamese_recognition/annotate_split.py blind_test

Opens the annotation page of the bake-off on the lines selected for that set
(``select_real_lines.py``) and stops by itself at the set's target of verified
lines: 400 for training, 100 for validation, 100 for the blind test. Work is
saved after every line and resumed by running the same command again.

The actions are the usual ones: the PP-OCRv6 text matches, the VietOCR text
matches, edit, type, skip, undo, save and quit. Nothing is accepted
automatically.

For ``blind_test`` the two predictions are hidden by default and every line is
typed from the image. Accepting a model's text is the fastest way to verify a
line and the easiest way to miss a wrong tone mark; on the bake-off lines that
tilted the ground truth towards the model it was copied from. A blind test
must not lean towards any model. ``--show-predictions`` brings them back.
"""

from __future__ import annotations

import argparse
import sys

import dataset_common as dataset
from dataset_common import BLIND_TEST, REAL_SPLITS

import annotate  # noqa: E402  (path set up by dataset_common)
from select_real_lines import VERIFIED_TARGET  # noqa: E402


def parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("split", choices=REAL_SPLITS)
    parser.add_argument("--show-predictions", action="store_true", help="Show the predictions for blind_test too.")
    parser.add_argument("--hide-predictions", action="store_true", help="Hide the predictions for any set.")
    parser.add_argument("--target", type=int, default=None, help="Verified lines to stop at (default: the set's target).")
    return parser.parse_known_args(argv)  # everything else goes to annotate.py (--cli, --port, --id ...)


def main(argv: list[str] | None = None) -> int:
    args, passed_on = parse_args(argv)
    directory = dataset.REAL_ANNOTATION_DIR / args.split
    if not (directory / "manifest.tsv").is_file():
        raise SystemExit(f"No lines laid out for {args.split} yet. Run select_real_lines.py first.")
    hide = args.hide_predictions or (args.split == BLIND_TEST and not args.show_predictions)
    command = [
        "--manifest", str(dataset.REAL_LINES),
        "--annotation-dir", str(directory),
        "--target", str(args.target or VERIFIED_TARGET[args.split]),
        *(["--hide-predictions"] if hide else []),
        *passed_on,
    ]  # fmt: skip
    return annotate.main(command)


if __name__ == "__main__":
    sys.exit(main())

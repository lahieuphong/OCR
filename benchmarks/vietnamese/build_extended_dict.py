#!/usr/bin/env python3
"""Build the extended PP-OCRv6 dictionary for a later Vietnamese fine-tune.

Usage:
    python benchmarks/vietnamese/build_extended_dict.py            # write it
    python benchmarks/vietnamese/build_extended_dict.py --check    # verify it

The result is the original ``ppocrv6_dict.txt``, byte for byte, followed by the
Vietnamese letters it lacks (see ``audit_charset.py``), one per line, in code
point order. No original entry is moved, removed or rewritten, so every
original entry keeps its line number.

This file is for training only. The pretrained PP-OCRv6 model has no output
class for the appended letters: pointing its ``character_dict_path`` at this
file does not make it recognise them, it only mislabels its outputs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from audit_charset import PPOCRV6_DICT, missing_characters, read_dictionary, vietnamese_letters
from common import REPO_ROOT

EXTENDED_DICT = REPO_ROOT / "configs" / "vietnamese" / "ppocrv6_vi_ext_dict.txt"
VENDOR_DIR = REPO_ROOT / "PaddleOCR"


def extended_dictionary_bytes(original: bytes, additions: list[str]) -> bytes:
    """``original`` unchanged, then one line per character of ``additions``."""
    if not original.endswith(b"\n"):
        # Appending would otherwise glue the first new letter to the last entry.
        raise ValueError("the original dictionary does not end with a newline")
    return original + "".join(character + "\n" for character in additions).encode("utf-8")


def build(original_path: Path) -> bytes:
    additions = missing_characters(read_dictionary(original_path), vietnamese_letters())
    return extended_dictionary_bytes(original_path.read_bytes(), additions)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--original", type=Path, default=PPOCRV6_DICT)
    parser.add_argument("--output", type=Path, default=EXTENDED_DICT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Write nothing; fail if the output file differs from what would be built.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if VENDOR_DIR.resolve() in args.output.resolve().parents:
        raise SystemExit(f"Refusing to write inside the vendored {VENDOR_DIR.name}/ tree.")

    data = build(args.original)
    original_entries = len(read_dictionary(args.original))
    if args.check:
        if not args.output.is_file() or args.output.read_bytes() != data:
            print(f"OUT OF DATE: {args.output}")
            return 1
        print(f"up to date: {args.output}")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(data)
        print(f"wrote {args.output}")

    extended_entries = len(read_dictionary(args.output))
    print(f"original entries: {original_entries}")
    print(f"extended entries: {extended_entries} (+{extended_entries - original_entries})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

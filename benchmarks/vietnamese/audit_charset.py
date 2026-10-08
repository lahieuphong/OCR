#!/usr/bin/env python3
"""Which Vietnamese letters the PP-OCRv6 recognition dictionary cannot produce.

Usage:
    python benchmarks/vietnamese/audit_charset.py

Compares ``PaddleOCR/ppocr/utils/dict/ppocrv6_dict.txt`` with the complete
Vietnamese alphabet and lists every letter that has no entry. A recognition
model can only output characters of its dictionary, so each missing letter is
one the stock PP-OCRv6 model can never produce.

The reference alphabet is generated, not typed in: the 12 vowels combined with
the 6 tones, plus the 17 consonants, in both cases. Nothing here is a hardcoded
list of results.
"""

from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path

from common import REPO_ROOT

PPOCRV6_DICT = REPO_ROOT / "PaddleOCR" / "ppocr" / "utils" / "dict" / "ppocrv6_dict.txt"

# The 29 letters of the Vietnamese alphabet, split by whether they take a tone.
VOWELS = "aăâeêioôơuưy"
CONSONANTS = "bcdđghklmnpqrstvx"
# Combining marks of the five written tones; the sixth tone (ngang) has none.
TONE_MARKS = {
    "ngang": "",
    "huyền": "̀",
    "sắc": "́",
    "hỏi": "̉",
    "ngã": "̃",
    "nặng": "̣",
}
# Marks a Vietnamese letter could be composed from if a dictionary held them.
COMBINING_MARKS = "̛̣̀́̃̉̂̆"


def read_dictionary(path: Path) -> list[str]:
    """Entries of a PaddleOCR character dictionary, in class order.

    Parsed exactly like ``BaseRecLabelDecode`` in
    ``PaddleOCR/ppocr/postprocess/rec_postprocess.py``: one entry per line, with
    only the line terminator removed, so an entry made of whitespace survives.
    """
    with path.open("rb") as stream:
        return [line.decode("utf-8").strip("\n").strip("\r\n") for line in stream]


def vietnamese_letters() -> list[str]:
    """Every letter of the Vietnamese alphabet in NFC, lowercase then uppercase."""
    lowercase = []
    for vowel in VOWELS:
        for mark in TONE_MARKS.values():
            letter = unicodedata.normalize("NFC", vowel + mark)
            if len(letter) != 1:
                raise ValueError(f"{vowel!r} + U+{ord(mark):04X} has no precomposed form")
            lowercase.append(letter)
    lowercase.extend(CONSONANTS)
    return lowercase + [letter.upper() for letter in lowercase]


def has_diacritic(letter: str) -> bool:
    return len(unicodedata.normalize("NFD", letter)) > 1 or letter in "đĐ"


def missing_characters(dictionary: list[str], reference: list[str]) -> list[str]:
    """Reference characters without a dictionary entry, in code point order."""
    entries = set(dictionary)
    return sorted(set(reference) - entries)


def code_point(character: str) -> str:
    return f"U+{ord(character):04X}"


def audit(dictionary_path: Path) -> dict:
    dictionary = read_dictionary(dictionary_path)
    reference = vietnamese_letters()
    missing = missing_characters(dictionary, reference)
    return {
        "dictionary_path": dictionary_path,
        "dictionary": dictionary,
        "reference": reference,
        "missing": missing,
        "combining_marks_present": [m for m in COMBINING_MARKS if m in set(dictionary)],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dict", type=Path, default=PPOCRV6_DICT, dest="dictionary")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = audit(args.dictionary)
    reference, missing = result["reference"], result["missing"]
    accented = [letter for letter in reference if has_diacritic(letter)]
    present = [letter for letter in accented if letter not in missing]

    print(f"dictionary:                     {args.dictionary}")
    print(f"existing dictionary entries:    {len(result['dictionary'])}")
    print(f"Vietnamese reference characters: {len(reference)}")
    print(f"  of which carry a diacritic:   {len(accented)}")
    print(f"  accented letters present:     {len(present)}  {''.join(sorted(present))}")
    print(f"missing count:                  {len(missing)}")
    print(f"missing characters:             {''.join(missing)}")
    marks = result["combining_marks_present"]
    print(
        "combining tone/vowel marks in the dictionary: "
        + (", ".join(code_point(m) for m in marks) if marks else "none")
        + " (a missing letter cannot be composed from a base letter and a mark)"
    )
    print()
    print("char\tcode point\tUnicode name")
    for character in missing:
        print(f"{character}\t{code_point(character)}\t{unicodedata.name(character)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

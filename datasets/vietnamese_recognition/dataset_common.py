"""Shared definitions for the Vietnamese recognition dataset.

Paths, the canonical manifest schema, plain TSV readers and writers, and the
frozen test holdout. The holdout is the one thing every other script must
respect: its lines never enter training or validation.
"""

from __future__ import annotations

import csv
import hashlib
import os
import sys
import unicodedata
from pathlib import Path

DATASET_DIR = Path(__file__).resolve().parent
REPO_ROOT = DATASET_DIR.parents[1]
BENCHMARK_DIR = REPO_ROOT / "benchmarks" / "vietnamese"
BAKEOFF_DIR = BENCHMARK_DIR / "recognizer_bakeoff"

for directory in (BENCHMARK_DIR, BAKEOFF_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

HOLDOUT_DIR = DATASET_DIR / "test_holdout"
HOLDOUT = HOLDOUT_DIR / "test_holdout.tsv"
HOLDOUT_LOCK = HOLDOUT_DIR / "test_holdout.sha256"
MANIFESTS_DIR = DATASET_DIR / "manifests"
HARD_CASES = MANIFESTS_DIR / "hard_cases.txt"
REAL_ANNOTATION_DIR = DATASET_DIR / "real_annotation"
VIETOCR_CONFIG_DIR = REPO_ROOT / "configs" / "vietnamese" / "vietocr"
VIETOCR_DIR = REPO_ROOT / "third_party" / "vietocr"

TRAIN, VAL, TEST = "train", "val", "test"
SPLITS = (TRAIN, VAL, TEST)
REAL, SYNTHETIC, HARD_CASE = "real", "synthetic", "hard_case"
SOURCE_TYPES = (REAL, SYNTHETIC, HARD_CASE)
LONG_LINE = "long_line"

# The canonical manifest: one row per line image.
CANONICAL_COLUMNS = (
    "id",
    "source_document",
    "page",
    "line_index",
    "image_path",  # relative to this directory
    "text",  # the label, UTF-8 NFC
    "split",
    "source_type",
    "verified",  # the label is known to be right: checked by a person, or synthetic
    "crop_sha256",  # SHA-256 of the image file
)
# Bookkeeping the long-line analysis and the audit need.
EXTRA_COLUMNS = ("image_width", "image_height", "subset", "font", "clean_image_path")
MANIFEST_COLUMNS = CANONICAL_COLUMNS + EXTRA_COLUMNS

HOLDOUT_COLUMNS = (
    "id",
    "document",
    "page",
    "line_index",
    "ground_truth",
    "crop_sha256",
    "split",
    "frozen",
)


def manifest_path(split: str) -> Path:
    return MANIFESTS_DIR / f"{split}.tsv"


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_text_atomic(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(data)
    os.replace(temporary, path)


def read_table(path: Path, columns: tuple[str, ...]) -> list[dict]:
    """Rows of a plain TSV file: fields hold no tab and follow no quoting rule."""
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
        if tuple(reader.fieldnames or ()) != columns:
            raise SystemExit(f"{path}: unexpected columns {reader.fieldnames}")
        return [{column: row[column] or "" for column in columns} for row in reader]


def write_table(path: Path, columns: tuple[str, ...], rows: list[dict]) -> None:
    lines = ["\t".join(columns)]
    for row in rows:
        fields = [str(row[column]) for column in columns]
        if any(separator in field for field in fields for separator in "\t\r\n"):
            raise ValueError(f"{row['id']}: a field contains a tab or a line break")
        lines.append("\t".join(fields))
    write_text_atomic(path, "\n".join(lines) + "\n")


def read_manifest(path: Path) -> list[dict]:
    return read_table(path, MANIFEST_COLUMNS)


def write_manifest(path: Path, rows: list[dict]) -> None:
    write_table(path, MANIFEST_COLUMNS, rows)


def manifest_row(**fields: object) -> dict:
    """A manifest row with every column present; unknown names are an error."""
    unknown = set(fields) - set(MANIFEST_COLUMNS)
    if unknown:
        raise KeyError(f"not manifest columns: {sorted(unknown)}")
    return {column: fields.get(column, "") for column in MANIFEST_COLUMNS}


def load_holdout(path: Path = HOLDOUT, lock: Path = HOLDOUT_LOCK) -> list[dict]:
    """The frozen test lines, after checking the file is the one that was frozen.

    The lock file holds the SHA-256 of the holdout as it was written. A holdout
    that no longer matches was edited after the fact and must not be used.
    """
    if not path.is_file() or not lock.is_file():
        raise SystemExit(f"No frozen holdout at {path}. Run freeze_test_holdout.py first.")
    if sha256_file(path) != lock.read_text(encoding="utf-8").split()[0]:
        raise SystemExit(f"{path} differs from the frozen version recorded in {lock.name}.")
    rows = read_table(path, HOLDOUT_COLUMNS)
    if any(row["split"] != TEST or row["frozen"] != "true" for row in rows):
        raise SystemExit(f"{path}: every holdout row must be split=test, frozen=true.")
    return rows


class Holdout:
    """What must never reach training or validation."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.ids = {row["id"] for row in rows}
        self.hashes = {row["crop_sha256"] for row in rows}
        self.texts = {nfc(row["ground_truth"]) for row in rows}

    @classmethod
    def load(cls) -> "Holdout":
        return cls(load_holdout())

    def leaks(self, rows: list[dict]) -> list[str]:
        """Reasons why ``rows`` (train or validation) contain a frozen test line."""
        problems = []
        for row in rows:
            if row["id"] in self.ids:
                problems.append(f"{row['id']}: id of a frozen test line")
            elif row["crop_sha256"] and row["crop_sha256"] in self.hashes:
                problems.append(f"{row['id']}: image of a frozen test line (same SHA-256)")
        return problems

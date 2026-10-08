"""Shared definitions for the Vietnamese recognition dataset.

Paths, the six sets of the dataset, the canonical manifest schema, the registry
of real source documents and the frozen evaluation sets.

Two rules run through every script here:

    - a real source document belongs to exactly one set, with all its lines;
    - frozen evaluation lines never enter training or validation.
"""

from __future__ import annotations

import csv
import hashlib
import os
import sys
import unicodedata
from collections import Counter
from pathlib import Path

DATASET_DIR = Path(__file__).resolve().parent
REPO_ROOT = DATASET_DIR.parents[1]
BENCHMARK_DIR = REPO_ROOT / "benchmarks" / "vietnamese"
BAKEOFF_DIR = BENCHMARK_DIR / "recognizer_bakeoff"

for directory in (BENCHMARK_DIR, BAKEOFF_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

MANIFESTS_DIR = DATASET_DIR / "manifests"
HARD_CASES = MANIFESTS_DIR / "hard_cases.txt"
VIETOCR_CONFIG_DIR = REPO_ROOT / "configs" / "vietnamese" / "vietocr"
VIETOCR_DIR = REPO_ROOT / "third_party" / "vietocr"

# --- the six sets ------------------------------------------------------------
REAL_TRAIN, REAL_VAL = "real_train", "real_val"
SYNTHETIC_TRAIN, SYNTHETIC_VAL = "synthetic_train", "synthetic_val"
# The 100 lines the recognizer was chosen on. They selected the model and their
# errors shaped the hard cases, so they measure regression, not final quality.
BAKEOFF_REGRESSION = "bakeoff_regression"
# Lines of documents nothing was tuned on. Scored once, at the very end.
BLIND_TEST = "blind_test"
SPLITS = (REAL_TRAIN, REAL_VAL, SYNTHETIC_TRAIN, SYNTHETIC_VAL, BAKEOFF_REGRESSION, BLIND_TEST)
TRAINING_SPLITS = (REAL_TRAIN, SYNTHETIC_TRAIN)
VALIDATION_SPLITS = (REAL_VAL, SYNTHETIC_VAL)
LEARNING_SPLITS = TRAINING_SPLITS + VALIDATION_SPLITS
REAL_SPLITS = (REAL_TRAIN, REAL_VAL, BLIND_TEST)

REAL, SYNTHETIC, HARD_CASE = "real", "synthetic", "hard_case"
SOURCE_TYPES = (REAL, SYNTHETIC, HARD_CASE)
LONG_LINE = "long_line"

# --- real documents ----------------------------------------------------------
REAL_SOURCE_DIR = DATASET_DIR / "real_source"  # new documents are dropped here
REAL_WORK_DIR = DATASET_DIR / "real_work"  # everything derived from them
DOCUMENTS = DATASET_DIR / "real_documents.tsv"
REAL_LINES = REAL_WORK_DIR / "manifest.jsonl"
REAL_ANNOTATION_DIR = REAL_WORK_DIR / "annotation"
LEGACY_DIR = DATASET_DIR / "legacy_candidates"
# What a document is assigned to, and the set its verified lines then form.
DOCUMENT_SPLITS = {"train": REAL_TRAIN, "val": REAL_VAL, "blind": BLIND_TEST}
DOCUMENT_COLUMNS = (
    "document_id",  # derived from the content hash, never from the file name
    "filename",
    "sha256",
    "page_count",
    "file_type",
    "source_note",
    "split",  # train, val, blind, or empty while unassigned
    "blind",
)

# --- frozen evaluation sets --------------------------------------------------
FROZEN_COLUMNS = (
    "id",
    "document",
    "page",
    "line_index",
    "ground_truth",
    "crop_sha256",
    "split",
    "frozen",
    "blind",
)
BENCHMARK_DOCUMENTS = DATASET_DIR / BAKEOFF_REGRESSION / "source_documents.tsv"

# --- the canonical manifest: one row per line image ----------------------------
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
# Bookkeeping the long-line analysis, the audit and the blind-test guard need.
EXTRA_COLUMNS = ("image_width", "image_height", "subset", "font", "clean_image_path", "blind")
MANIFEST_COLUMNS = CANONICAL_COLUMNS + EXTRA_COLUMNS


def manifest_path(split: str, root: Path = DATASET_DIR) -> Path:
    return root / "manifests" / f"{split}.tsv"


def frozen_path(name: str, root: Path = DATASET_DIR) -> Path:
    return root / name / f"{name}.tsv"


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
            raise ValueError(f"{row[columns[0]]}: a field contains a tab or a line break")
        lines.append("\t".join(fields))
    write_text_atomic(path, "\n".join(lines) + "\n")


def read_manifest(path: Path) -> list[dict]:
    return read_table(path, MANIFEST_COLUMNS)


def write_manifest(path: Path, rows: list[dict]) -> None:
    write_table(path, MANIFEST_COLUMNS, rows)


def read_splits(root: Path = DATASET_DIR) -> dict[str, list[dict]]:
    """Every set of the dataset; a set whose manifest does not exist yet is empty."""
    return {
        split: read_manifest(manifest_path(split, root)) if manifest_path(split, root).is_file() else []
        for split in SPLITS
    }


def manifest_row(**fields: object) -> dict:
    """A manifest row with every column present; unknown names are an error."""
    unknown = set(fields) - set(MANIFEST_COLUMNS)
    if unknown:
        raise KeyError(f"not manifest columns: {sorted(unknown)}")
    row = {column: fields.get(column, "") for column in MANIFEST_COLUMNS}
    row["blind"] = "true" if row["split"] == BLIND_TEST else "false"
    return row


# --- documents ---------------------------------------------------------------


def read_documents(path: Path = DOCUMENTS) -> list[dict]:
    return read_table(path, DOCUMENT_COLUMNS) if path.is_file() else []


def write_documents(rows: list[dict], path: Path = DOCUMENTS) -> None:
    write_table(path, DOCUMENT_COLUMNS, sorted(rows, key=lambda row: row["document_id"]))


def benchmark_documents(path: Path = BENCHMARK_DOCUMENTS) -> dict[str, str]:
    """SHA-256 -> name of the documents the bake-off was run on."""
    with path.open(encoding="utf-8", newline="") as stream:
        return {row["sha256"]: row["document"] for row in csv.DictReader(stream, delimiter="\t")}


def document_leaks(splits: dict[str, list[dict]]) -> list[str]:
    """Reasons why a source document has lines in more than one set.

    Only real lines carry a document; synthetic ones all share a generator
    name and are left out.
    """
    owners: dict[str, set[str]] = {}
    for split, rows in splits.items():
        for row in rows:
            if row["source_type"] == REAL:
                owners.setdefault(row["source_document"], set()).add(split)
    return [
        f"document {document} has lines in {' and '.join(sorted(sets))}"
        for document, sets in sorted(owners.items())
        if len(sets) > 1
    ]


# --- what a training run may read --------------------------------------------


def annotation_images(path: Path) -> list[str]:
    """Image paths of a VietOCR annotation file (``image<TAB>label`` per line)."""
    if not path.is_file():
        return []
    return [line.split("\t")[0] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def training_data_problems(train_annotation: Path, valid_annotation: Path, root: Path = DATASET_DIR) -> list[str]:
    """Reasons why a training run must not start from these two annotation files.

    Training may read ``real_train`` and ``synthetic_train``; validation may
    read ``real_val`` only, because the weights to keep are chosen on real
    lines. A line of the blind test or of the bake-off regression in either
    file is a leak, and so is an image no manifest knows.
    """
    owner = {row["image_path"]: split for split, rows in read_splits(root).items() for row in rows}
    problems = []
    for role, path, allowed in (
        ("training", train_annotation, TRAINING_SPLITS),
        ("validation", valid_annotation, (REAL_VAL,)),
    ):
        found = Counter(owner.get(image, "no set") for image in annotation_images(path))
        problems += [
            f"{role} file {path.name}: {count} line(s) of {split}"
            for split, count in sorted(found.items())
            if split not in allowed
        ]
    return problems


# --- frozen evaluation sets --------------------------------------------------


def load_frozen(name: str, path: Path | None = None, lock: Path | None = None) -> list[dict]:
    """The lines of a frozen set, after checking the file is the one that was frozen.

    The lock file holds the SHA-256 of the set as it was written. A file that
    no longer matches was edited after the fact and must not be used.
    """
    path = path or frozen_path(name)
    lock = lock or path.with_suffix(".sha256")
    if not path.is_file() or not lock.is_file():
        raise SystemExit(f"No frozen {name} at {path}.")
    if sha256_file(path) != lock.read_text(encoding="utf-8").split()[0]:
        raise SystemExit(f"{path} differs from the frozen version recorded in {lock.name}.")
    rows = read_table(path, FROZEN_COLUMNS)
    blind = "true" if name == BLIND_TEST else "false"
    if any((row["split"], row["frozen"], row["blind"]) != (name, "true", blind) for row in rows):
        raise SystemExit(f"{path}: every row must be split={name}, frozen=true, blind={blind}.")
    return rows


def labels_digest(rows: list[dict]) -> str:
    """SHA-256 over id, ground truth and crop hash of every line, in id order.

    It does not depend on the name of the set or on any other column, so it
    stays the same when a set is given a new role and changes when a label does.
    """
    text = "".join(
        f"{row['id']}\t{row['ground_truth']}\t{row['crop_sha256']}\n"
        for row in sorted(rows, key=lambda row: row["id"])
    )
    return sha256_bytes(text.encode("utf-8"))


class FrozenLines:
    """Evaluation lines that must never reach training or validation."""

    def __init__(self, name: str, rows: list[dict]) -> None:
        self.name, self.rows = name, rows
        self.ids = {row["id"] for row in rows}
        self.hashes = {row["crop_sha256"] for row in rows}
        self.texts = {nfc(row["ground_truth"]) for row in rows}
        self.documents = {row["document"] for row in rows}

    @classmethod
    def load(cls, name: str = BAKEOFF_REGRESSION, root: Path = DATASET_DIR) -> "FrozenLines":
        return cls(name, load_frozen(name, frozen_path(name, root)))

    def leaks(self, rows: list[dict]) -> list[str]:
        """Reasons why ``rows`` (of another set) contain one of these lines."""
        problems = []
        for row in rows:
            if row["id"] in self.ids:
                problems.append(f"{row['id']}: id of a {self.name} line")
            elif row["crop_sha256"] and row["crop_sha256"] in self.hashes:
                problems.append(f"{row['id']}: image of a {self.name} line (same SHA-256)")
        return problems

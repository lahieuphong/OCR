"""Shared definitions for the recognizer bake-off scripts.

Paths, the frozen detection profile, and readers/writers for the crop manifest,
the predictions and the annotation table. Standard library only: this module is
imported from both the PaddlePaddle and the VietOCR environment.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from pathlib import Path

BAKEOFF_DIR = Path(__file__).resolve().parent
BENCHMARK_DIR = BAKEOFF_DIR.parent

sys.path.insert(0, str(BENCHMARK_DIR))
from common import PROFILE_B, REPO_ROOT  # noqa: E402

# Detection and preprocessing are frozen to this profile so that both
# recognizers read the same crops. This is not a verdict on profile A versus B.
FROZEN_PROFILE = PROFILE_B

MANIFEST = BAKEOFF_DIR / "manifest.jsonl"
EXPORT_METADATA = BAKEOFF_DIR / "export_metadata.json"
CROPS_DIR = BAKEOFF_DIR / "crops"
PREDICTIONS_DIR = BAKEOFF_DIR / "predictions"
ANNOTATION_DIR = BAKEOFF_DIR / "annotation"
ANNOTATION_MANIFEST = ANNOTATION_DIR / "manifest.tsv"
ANNOTATION_LOG = ANNOTATION_DIR / "annotation_log.jsonl"
SELECTION_REPORT = ANNOTATION_DIR / "selection.json"
CANDIDATES_DIR = ANNOTATION_DIR / "candidates"
RESULTS_DIR = BAKEOFF_DIR / "results"
MODELS_DIR = REPO_ROOT / "models"

PPOCR = "ppocrv6"
VIETOCR = "vietocr"
PREDICTION_FILES = {
    PPOCR: PREDICTIONS_DIR / f"{PPOCR}.jsonl",
    VIETOCR: PREDICTIONS_DIR / f"{VIETOCR}.jsonl",
}

# The columns a freshly selected table starts from ...
SELECTION_COLUMNS = (
    "id",
    "document",
    "page",
    "crop_path",
    "ppocr_prediction",
    "vietocr_prediction",
    "ground_truth",
    "verified",
)
# ... and the ones the annotation tool fills in. `excluded_reason` marks a row a
# person looked at and set aside; such a row stays `verified=false`.
REVIEW_COLUMNS = (
    "excluded_reason",
    "ground_truth_source",
    "annotator",
    "verified_at",
    "ground_truth_sha256",
)
ANNOTATION_COLUMNS = SELECTION_COLUMNS + REVIEW_COLUMNS


def crop_id(document: str, page: int, line_index: int) -> str:
    """Identifier of a line crop; ``page`` and ``line_index`` are 1-based."""
    return f"{document}_p{page:04d}_l{line_index:04d}"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_text_atomic(path: Path, data: str) -> None:
    """Replace ``path`` in one step, so an interrupted write cannot truncate it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(data)
    os.replace(temporary, path)


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    write_text_atomic(
        path, "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    )


def write_json(path: Path, data: object) -> None:
    write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    repeated = []
    for value in values:
        if value in seen:
            repeated.append(value)
        seen.add(value)
    return repeated


def load_manifest(path: Path = MANIFEST) -> list[dict]:
    """Rows of the crop manifest; every id and every crop path must be unique."""
    if not path.is_file():
        raise SystemExit(f"No crop manifest at {path}. Run export_line_crops.py first.")
    rows = read_jsonl(path)
    for field in ("id", "crop_path"):
        repeated = duplicates([row[field] for row in rows])
        if repeated:
            raise SystemExit(f"{path}: duplicate {field}: {', '.join(repeated[:5])}")
    return rows


def verified_crop_path(row: dict, base_dir: Path = BAKEOFF_DIR) -> Path:
    """Path of a row's crop, after checking it is the file that was exported.

    Both recognizers go through this check, so neither can end up reading a
    crop that was regenerated or edited after the other one ran.
    """
    path = base_dir / row["crop_path"]
    if not path.is_file():
        raise SystemExit(f"Missing crop for {row['id']}: {path}")
    if sha256_file(path) != row["crop_sha256"]:
        raise SystemExit(f"Crop for {row['id']} differs from the exported one: {path}")
    return path


def write_predictions(path: Path, rows: list[dict], metadata: dict) -> None:
    """One ``{id, prediction, confidence, runtime_ms}`` record per crop."""
    write_jsonl(path, rows)
    write_json(path.with_suffix(".meta.json"), metadata)


def load_predictions(path: Path) -> dict[str, dict]:
    if not path.is_file():
        raise SystemExit(f"No predictions at {path}.")
    rows = read_jsonl(path)
    repeated = duplicates([row["id"] for row in rows])
    if repeated:
        raise SystemExit(f"{path}: duplicate id: {', '.join(repeated[:5])}")
    return {row["id"]: row for row in rows}


def check_same_ids(id_sets: dict[str, set[str]]) -> None:
    """Fail unless every named set holds exactly the same ids."""
    names = list(id_sets)
    reference = id_sets[names[0]]
    for name in names[1:]:
        other = id_sets[name]
        if other != reference:
            only_reference = sorted(reference - other)
            only_other = sorted(other - reference)
            raise SystemExit(
                f"FAIL: {names[0]} and {name} do not cover the same crops "
                f"({len(only_reference)} only in {names[0]}, e.g. {only_reference[:3]}; "
                f"{len(only_other)} only in {name}, e.g. {only_other[:3]})."
            )


def read_annotation(path: Path = ANNOTATION_MANIFEST) -> list[dict]:
    """Rows of the annotation table. Fields are plain text: no quoting rules.

    A table written before the review columns existed is accepted and gets
    them empty; it is upgraded the next time it is saved.
    """
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
        if tuple(reader.fieldnames or ()) not in (ANNOTATION_COLUMNS, SELECTION_COLUMNS):
            raise SystemExit(f"{path}: unexpected columns {reader.fieldnames}")
        rows = [{column: row.get(column) or "" for column in ANNOTATION_COLUMNS} for row in reader]
    repeated = duplicates([row["id"] for row in rows])
    if repeated:
        raise SystemExit(f"{path}: duplicate id: {', '.join(repeated[:5])}")
    return rows


def write_annotation(path: Path, rows: list[dict]) -> None:
    lines = ["\t".join(ANNOTATION_COLUMNS)]
    for row in rows:
        fields = [str(row[column]) for column in ANNOTATION_COLUMNS]
        for field in fields:
            # A tab or line break inside a field would shift every later column.
            if any(separator in field for separator in "\t\r\n"):
                raise ValueError(f"{row['id']}: a field contains a tab or a line break")
        lines.append("\t".join(fields))
    write_text_atomic(path, "\n".join(lines) + "\n")


def is_verified(row: dict) -> bool:
    return row["verified"] == "true"


def is_excluded(row: dict) -> bool:
    """Looked at by a person and set aside: never scored."""
    return not is_verified(row) and bool(row["excluded_reason"])


def is_pending(row: dict) -> bool:
    return not is_verified(row) and not row["excluded_reason"]


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

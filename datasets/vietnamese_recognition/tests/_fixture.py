"""A small dataset on disk for tests: documents, exported lines, annotation, manifests.

Nothing here runs a detector or renders text. Crops are files with arbitrary
bytes, which is all the bookkeeping under test ever looks at.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import _paths  # noqa: F401
import build_dataset
import dataset_common as dataset
from dataset_common import SYNTHETIC_TRAIN, SYNTHETIC_VAL

import bakeoff_common as bakeoff
from audit_charset import vietnamese_letters

VOCABULARY = build_dataset.recognizer_vocabulary()


def document_id(name: str) -> str:
    return f"doc_{dataset.sha256_bytes(name.encode())[:12]}"


class Workspace:
    """A dataset root in a temporary directory."""

    def __init__(self, test: unittest.TestCase, documents: dict[str, tuple[str, int]]) -> None:
        directory = tempfile.TemporaryDirectory()
        test.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.documents_path = self.root / "real_documents.tsv"
        self.work_dir = self.root / "real_work"
        self.legacy_dir = self.root / "legacy_candidates"
        (self.work_dir / "crops").mkdir(parents=True)
        self.write_documents(documents)
        self.lines = []
        for name, (_, count) in documents.items():
            self.add_lines(name, count)
        self.save_lines()
        self.write_synthetic()

    # --- documents and their lines ---------------------------------------------

    def write_documents(self, documents: dict[str, tuple[str, int]]) -> None:
        dataset.write_documents(
            [
                {
                    "document_id": document_id(name),
                    "filename": f"{name}.pdf",
                    "sha256": dataset.sha256_bytes(name.encode()),
                    "page_count": 1,
                    "file_type": "pdf",
                    "source_note": "test fixture",
                    "split": split,
                    "blind": "true" if split == "blind" else "false",
                }
                for name, (split, _) in documents.items()
            ],
            self.documents_path,
        )

    def add_lines(self, name: str, count: int) -> None:
        identifier = document_id(name)
        for index in range(1, count + 1):
            key = bakeoff.crop_id(identifier, 1 + (index - 1) // 20, index)
            crop = self.work_dir / "crops" / f"{key}.png"
            crop.write_bytes(f"crop of {key}".encode())
            text = f"{name} dòng thứ {index}, ngày 05 tháng 02 năm 2025"
            self.lines.append(
                {
                    "id": key, "document": identifier, "document_id": identifier,
                    "page": 1 + (index - 1) // 20, "line_index": index,
                    "polygon": [[0, 0], [400, 0], [400, 30], [0, 30]],
                    "paddle_prediction": text.replace("ứ", "").replace("ò", "o"), "paddle_confidence": 0.9,
                    "textline_orientation_angle": 0, "crop_path": f"crops/{key}.png",
                    "crop_sha256": dataset.sha256_file(crop),
                    "width": 400 + index, "height": 30, "aspect_ratio": round((400 + index) / 30, 3),
                    "crop_width": 400 + index, "crop_height": 30, "true_text": text,
                }
            )  # fmt: skip

    def save_lines(self) -> None:
        bakeoff.write_jsonl(self.work_dir / "manifest.jsonl", [{k: v for k, v in line.items() if k != "true_text"} for line in self.lines])
        bakeoff.write_jsonl(
            self.work_dir / "predictions" / "vietocr.jsonl",
            [{"id": line["id"], "prediction": line["true_text"], "confidence": 0.95, "runtime_ms": 1} for line in self.lines],
        )

    # --- annotation --------------------------------------------------------------

    def annotate(self, split: str, names: list[str], verified_per_document: int, text=None) -> None:
        """Lay out every line of ``names`` for ``split`` and verify the first few of each."""
        rows = []
        for name in names:
            lines = [line for line in self.lines if line["document_id"] == document_id(name)]
            for position, line in enumerate(lines):
                truth = (text(line) if text else line["true_text"]) if position < verified_per_document else ""
                rows.append(
                    {
                        "id": line["id"], "document": line["document_id"], "page": str(line["page"]),
                        "crop_path": line["crop_path"], "ppocr_prediction": line["paddle_prediction"],
                        "vietocr_prediction": line["true_text"], "ground_truth": truth,
                        "verified": "true" if truth else "false", "excluded_reason": "",
                        "ground_truth_source": "typed" if truth else "", "annotator": "tester" if truth else "",
                        "verified_at": "2026-01-01T00:00:00+00:00" if truth else "",
                        "ground_truth_sha256": bakeoff.text_sha256(truth) if truth else "",
                    }
                )  # fmt: skip
        bakeoff.write_annotation(self.work_dir / "annotation" / split / "manifest.tsv", rows)

    # --- synthetic sets ----------------------------------------------------------

    def write_synthetic(self) -> None:
        letters = vietnamese_letters()
        chunks = [" ".join(letters[start : start + 40]) for start in range(0, len(letters), 40)]
        for split, folder, texts in (
            (SYNTHETIC_TRAIN, "train", chunks + ["Căn cứ Luật Tổ chức Chính phủ"]),
            (SYNTHETIC_VAL, "val", ["Thực hiện Nghị quyết của Chính phủ", "Số: 15/2024/NĐ-CP"]),
        ):
            rows = []
            for index, text in enumerate(texts, start=1):
                key = f"syn_{folder}_{index:06d}"
                paths = {}
                for kind in ("images", "clean"):
                    path = self.root / folder / kind / f"{key}.png"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(f"{kind} of {key}".encode())
                    paths[kind] = path
                rows.append(
                    dataset.manifest_row(
                        id=key, source_document="synthetic/test", image_path=f"{folder}/images/{key}.png", text=text,
                        split=split, source_type="synthetic", verified="true",
                        crop_sha256=dataset.sha256_file(paths["images"]), image_width=600, image_height=30,
                        font="Times New Roman", clean_image_path=f"{folder}/clean/{key}.png",
                    )
                )  # fmt: skip
            dataset.write_manifest(dataset.manifest_path(split, self.root), rows)

    # --- the scripts under test ------------------------------------------------

    def arguments(self) -> list[str]:
        return ["--root", str(self.root), "--documents", str(self.documents_path), "--work-dir", str(self.work_dir)]

    def build(self, *extra: str) -> int:
        return build_dataset.main(["--skip-synthetic", *self.arguments(), *extra])

    def audit(self, **options) -> dict:
        import audit_dataset

        return audit_dataset.audit(self.root, VOCABULARY, self.documents_path, self.work_dir, self.legacy_dir, **options)

    def splits(self) -> dict[str, list[dict]]:
        return dataset.read_splits(self.root)

    def rewrite(self, split: str, change) -> None:
        rows = dataset.read_manifest(dataset.manifest_path(split, self.root))
        change(rows)
        dataset.write_manifest(dataset.manifest_path(split, self.root), rows)

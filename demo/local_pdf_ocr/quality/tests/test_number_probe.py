"""Synthetic, model-free tests for document-number discovery and strict gates."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from demo.local_pdf_ocr.quality.number_fields import (
    NUMBER_HEADER, is_document_number, select_number_headers,
)
from demo.local_pdf_ocr.quality.number_probe import (
    decide_larger_trial, select_field_samples, summarize_variants, validate_groups,
    infer_verified,
)


def row(index, text, *, y=200, width=1200, height=1700):
    return {
        "line_index": index, "text": text,
        "polygon": [[150, y], [390, y], [390, y + 32], [150, y + 32]],
    }


def observation(identifier, reference, baseline, contrast, unsharp):
    return {
        "id": identifier,
        "reference": reference,
        "predictions": {
            "baseline": baseline, "contrast_1p15": contrast,
            "unsharp_light": unsharp,
        },
    }


class HeaderSelectionTests(unittest.TestCase):
    def test_selects_document_numbers_without_reference_or_corrected_text(self):
        page = {
            "page": 1, "width": 1200, "height": 1700,
            "lines": [
                row(8, "BỘ CÔNG THƯƠNG"),
                row(9, "Số: RU8/TB-VPCP", y=350),
                row(10, "Số: 37/2025/TT-BCT", y=405),
                row(12, "số điều của Luật Mẫu được sửa đổi", y=530),
                row(24, "SỐ 64/2022/NĐ-CP", y=840),
                row(25, "Căn cứ số 64/2022/NĐ-CP", y=915),
            ],
        }
        self.assertEqual(
            [x["line_index"] for x in select_number_headers(page)],
            [9, 10],
        )
        self.assertEqual(select_number_headers({**page, "page": 2}), [])
        self.assertTrue(NUMBER_HEADER.match("Số: 815/QĐ-TTg"))
        self.assertFalse(NUMBER_HEADER.match("Theo số 815/QĐ-TTg"))
        self.assertFalse(NUMBER_HEADER.match("số điều của Luật Mẫu"))
        with self.assertRaisesRegex(ValueError, "never silently trim"):
            select_number_headers(page, limit=1)

    def test_legacy_manifest_without_page_dimensions_uses_early_line_guard(self):
        r = row(9, "Số: RU8/TB-VPCP")
        self.assertTrue(is_document_number(
            {**r, "ocr_prediction": r["text"]}, page=1))
        late = row(24, "SỐ 64/2022/NĐ-CP")
        self.assertFalse(is_document_number(
            {**late, "ocr_prediction": late["text"]}, page=1))


class ProbeGatesTests(unittest.TestCase):
    def test_no_per_line_regression_and_strict_holdout_improvement_required(self):
        calibrate = summarize_variants([
            observation("old", "Số: 218", "Số: RU8", "Số: 218", "Số: 218"),
            observation("old2", "Số: 37", "Số: 37", "Số: 37", "Số: 37"),
            observation("old3", "Số: 815", "Số: 815", "Số: 815", "Số: 815"),
        ])
        # Five independent PDF documents and no changes: insufficient improvement.
        held = summarize_variants([
            observation(f"new{i}", f"Số: {i}", f"Số: {i}", f"Số: {i}", f"Số: {i}")
            for i in range(5)
        ])
        split = {
            "independent_holdout_gate_met": True,
            "calibration_documents": 3, "holdout_documents": 5,
        }
        decision = decide_larger_trial(calibrate, held, split)
        self.assertFalse(decision["eligible_for_larger_trial"])
        self.assertEqual(decision["status"], "NO_GO_FOR_LARGER_TRIAL")

        # Test an actual independent correction without any regressions.
        independent = summarize_variants([
            observation("new0", "Số: 999", "Số: 99X", "Số: 999", "Số: 999"),
            *[
                observation(f"new{i}", f"Số: {i}", f"Số: {i}", f"Số: {i}", f"Số: {i}")
                for i in range(1, 5)
            ],
        ])
        decision = decide_larger_trial(calibrate, independent, split)
        self.assertTrue(decision["eligible_for_larger_trial"])
        self.assertEqual(decision["status"], "ELIGIBLE_FOR_LARGER_TRIAL_NOT_DEPLOYMENT")
        split["independent_holdout_gate_met"] = False
        self.assertFalse(decide_larger_trial(calibrate, independent, split)["eligible_for_larger_trial"])

    def test_worsened_one_line_vetoes_even_when_total_improves(self):
        trial = summarize_variants([
            observation("gain", "Số: 218", "Số: RU8", "Số: 218", "Số: 218"),
            observation("loss", "Số: 815", "Số: 815", "Số: 816", "Số: 815"),
        ])
        self.assertEqual(
            trial["candidate_analysis"]["contrast_1p15"]["regressed_line_ids"],
            ["loss"],
        )
        self.assertFalse(trial["candidate_analysis"]["contrast_1p15"]["no_regressions"])

    def test_same_pdf_sha_must_not_be_both_calibration_and_holdout(self):
        data = {
            "document": "a.pdf", "pdf_sha256": "a" * 64, "id": "one",
        }
        with self.assertRaisesRegex(ValueError, "share PDF content"):
            validate_groups([data], [{**data, "id": "other"}])
        fine = validate_groups([data], [{
            "document": "b.pdf", "pdf_sha256": "b" * 64, "id": "two",
        }])
        self.assertFalse(fine["independent_holdout_gate_met"])

    def test_infer_bails_before_enhancement_when_parity_is_broken(self):
        with tempfile.TemporaryDirectory() as folder:
            picture = Path(folder) / "crop.png"
            Image.new("RGB", (100, 25), "white").save(picture)
            sample = {
                "id": "wrong", "_crop_path": picture,
                "ocr_prediction": "Số: 218",
            }
            class BadRecognizer:
                def predict(self, img):
                    return "Số: RU8", False
            with self.assertRaisesRegex(RuntimeError, "parity mismatch"):
                infer_verified([sample], BadRecognizer())

    def test_field_selection_requires_preverified_human_label(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "crops").mkdir()
            png = root / "crops" / "one.png"
            Image.new("RGB", (100, 25), "white").save(png)
            digest = hashlib.sha256(png.read_bytes()).hexdigest()
            entry = {
                "id": "one", "document": "doc.pdf",
                "page": 1, "line_index": 9,
                "polygon": row(9, "Số: RU8")["polygon"],
                "ocr_prediction": "Số: RU8/TB-VPCP",
                "pdf_sha256": "d" * 64,
                "crop_path": "crops/one.png",
                "crop_sha256": digest,
            }
            (root / "manifest.jsonl").write_text(json.dumps(entry)+"\n", encoding="utf-8")
            label = {"id": "one", "crop_sha256": digest, "reference": None, "verified": False}
            (root / "labels.jsonl").write_text(json.dumps(label)+"\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "remain unverified"):
                select_field_samples(root)
            label["reference"], label["verified"] = "Số: 218/TB-VPCP", True
            (root / "labels.jsonl").write_text(
                json.dumps(label, ensure_ascii=False)+"\n", encoding="utf-8"
            )
            result = select_field_samples(root)
            self.assertEqual(result[0]["reference"], "Số: 218/TB-VPCP")
            self.assertEqual(result[0]["pdf_sha256"], "d" * 64)


if __name__ == "__main__":
    unittest.main()

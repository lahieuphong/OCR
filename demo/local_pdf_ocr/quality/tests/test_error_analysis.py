"""Private-safe synthetic tests for OCR error analysis; no model needed."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from demo.local_pdf_ocr.backend.contract import CHECKPOINT_SHA256
from demo.local_pdf_ocr.quality.benchmark import metrics
from demo.local_pdf_ocr.quality.error_analysis import (
    build_report, difference_tags, edits, render_html,
)


def write_jsonl(path, records):
    path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records),
        encoding="utf-8",
    )


class ErrorAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "crops").mkdir()
        info = [
            ("a1", "Nghi đinh", "Nghị định", "a.pdf"),
            ("b1", "Chuẩn", "Chuẩn", "b.pdf"),
            ("c1", "Số 121", "Số 123", "c.pdf"),
        ]
        self.manifest, self.labels = [], []
        for ident, predicted, reference, doc in info:
            crop = self.root / "crops" / (ident + ".png")
            Image.new("RGB", (140, 40), "white").save(crop)
            digest = hashlib.sha256(crop.read_bytes()).hexdigest()
            self.manifest.append({
                "id": ident, "document": doc, "page": 1, "line_index": 1,
                "crop_path": "crops/" + ident + ".png",
                "crop_sha256": digest, "ocr_prediction": predicted,
            })
            self.labels.append({
                "id": ident, "crop_sha256": digest,
                "reference": reference, "verified": True,
            })
        write_jsonl(self.root / "manifest.jsonl", self.manifest)
        write_jsonl(self.root / "labels.jsonl", self.labels)
        self.report = {
            "status": "EXPERIMENT_ONLY_NO_DEPLOYMENT_APPROVAL",
            "blind_test_used": False,
            "baseline_reproduced_exactly": True,
            "samples_human_verified": 3,
            "frozen_checkpoint_sha256": CHECKPOINT_SHA256,
            "scores": {"baseline": metrics([
                (entry["reference"], row["ocr_prediction"])
                for entry, row in zip(self.labels, self.manifest)
            ])},
            "candidate_assessment": {
                "contrast_1p15": {
                    "new_regression_line_ids": ["b1"]
                },
                "unsharp_light": {
                    "new_regression_line_ids": ["c1", "b1"]
                },
                "autocontrast_1pct": {
                    "new_regression_line_ids": []
                },
            },
        }
        self.write_report()

    def write_report(self):
        (self.root / "benchmark_report.json").write_text(
            json.dumps(self.report, ensure_ascii=False), encoding="utf-8"
        )

    def test_classification_is_observed_not_root_cause(self):
        self.assertIn("diacritic_only", difference_tags("triển", "triên"))
        self.assertIn("digit_sequence_differs", difference_tags("Số 216", "Số 218"))
        self.assertEqual(difference_tags("Đúng", "Đúng"), ["unchanged"])
        self.assertTrue(edits("CỘNG HÒA", "CÔNG HÒA"))

    def test_analysis_selects_all_bad_lines_and_unchanged_regression(self):
        result = build_report(self.root, min_verified=1)
        summary = result["summary"]
        self.assertEqual(summary["baseline_errors"], 2)
        self.assertEqual(summary["all_verified_lines"], 3)
        self.assertEqual(summary["distinct_lines_in_report"], 3)
        self.assertEqual(summary["reviewed_candidate_regression_ids"], 1)
        self.assertFalse(summary["candidate_inference_performed"])
        unchanged = next(row for row in result["lines"] if row["id"] == "b1")
        self.assertEqual(unchanged["baseline_char_errors"], 0)
        self.assertIn("unsharp_light", unchanged["regressed_variants_previous"])
        self.assertIsNone(unchanged["root_cause"])

    def test_stale_annotations_must_not_reuse_old_regression_evidence(self):
        self.labels[0]["reference"] = "Nghị đinh"
        write_jsonl(self.root / "labels.jsonl", self.labels)
        with self.assertRaisesRegex(ValueError, "labels or predictions differ"):
            build_report(self.root, min_verified=1)

    def test_bad_regression_id_fail_closed(self):
        self.report["candidate_assessment"]["unsharp_light"]["new_regression_line_ids"] = ["unknown"]
        self.write_report()
        with self.assertRaisesRegex(ValueError, "absent"):
            build_report(self.root, min_verified=1)

    def test_html_escapes_user_confirmed_text_and_does_not_have_scripts(self):
        result = build_report(self.root, min_verified=1)
        result["lines"][0]["reference"] = "<img src=x onerror=alert(1)>"
        markup = render_html(result)
        self.assertNotIn("<img src=x onerror", markup)
        self.assertIn("&lt;img", markup)
        self.assertNotIn("<script", markup)
        self.assertIn('src="crops/a1.png"', markup)

    def test_optional_model_is_not_loaded_in_default_mode(self):
        with patch(
            "demo.local_pdf_ocr.quality.error_analysis.infer_selected",
            side_effect=AssertionError("Inference must not run by default"),
        ):
            result = build_report(self.root, min_verified=1)
        self.assertFalse(result["summary"]["selected_baseline_reproduced"])


if __name__ == "__main__":
    unittest.main()

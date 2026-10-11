"""Model-free, private-data-free tests for human region review and candidates."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from demo.local_pdf_ocr.quality.benchmark import metrics, verified_samples
from demo.local_pdf_ocr.quality.review_server import ReviewStore
from demo.local_pdf_ocr.quality.zone_audit import (
    build_zone_audit, candidate_ledger, normalized_region, render_html,
)


def jsonl(path, rows):
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )


class ZoneAuditTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "crops").mkdir()
        specs = [
            ("a", "Số: RU6/TB-VPCP", "Số: 216/TB-VPCP"),
            ("b", "CÓNG", "TƯỚNG"),
            ("c", "4", "4"),
        ]
        self.samples = []
        self.labels = []
        for ident, ocr, reference in specs:
            crop = self.root / "crops" / (ident + ".png")
            Image.new("RGB", (100, 30), "white").save(crop)
            checksum = hashlib.sha256(crop.read_bytes()).hexdigest()
            self.samples.append({
                "id": ident, "document": "example.pdf", "page": 1,
                "line_index": len(self.samples) + 1,
                "crop_path": "crops/" + ident + ".png",
                "crop_sha256": checksum, "ocr_prediction": ocr,
            })
            self.labels.append({
                "id": ident, "crop_sha256": checksum,
                "reference": reference, "verified": True,
            })
        jsonl(self.root / "manifest.jsonl", self.samples)
        jsonl(self.root / "labels.jsonl", self.labels)
        # Synthetic prior targeted re-inference on one line.
        detail = {
            "summary": {
                "no_blind_test": True,
                "selected_baseline_reproduced": True,
                "candidate_inference_performed": True,
            },
            "lines": [{
                "id": "a", "reference": "Số: 216/TB-VPCP",
                "baseline": "Số: RU6/TB-VPCP",
                "crop_sha256": self.samples[0]["crop_sha256"],
                "variants": {
                    "contrast_1p15": {
                        "prediction": "Số: 216/TB-VPCP",
                        "char_errors": 0, "word_errors": 0,
                    },
                    "unsharp_light": {
                        "prediction": "Số: 216/TB-VPCP",
                        "char_errors": 0, "word_errors": 0,
                    },
                },
            }],
        }
        (self.root / "error_analysis.json").write_text(
            json.dumps(detail, ensure_ascii=False), encoding="utf-8",
        )
        self.old_metrics = metrics([
            (label["reference"], row["ocr_prediction"])
            for label, row in zip(self.labels, self.samples)
        ])

    def test_region_types_must_be_explicit_and_valid(self):
        self.assertEqual(normalized_region(self.labels[0]), "unreviewed")
        self.assertEqual(normalized_region({"region_type": "stamp_artifact",
                                            "region_reviewed": True}), "stamp_artifact")
        with self.assertRaises(ValueError):
            normalized_region({"region_type": "stamp_artifact", "region_reviewed": False})
        with self.assertRaises(ValueError):
            normalized_region({"region_type": "forged", "region_reviewed": True})

    def test_region_save_does_not_modify_verified_or_reference(self):
        store = ReviewStore(self.root)
        before = store.samples()["rows"][1]
        answer = store.save("b", "classify", region_type="stamp_overlap")
        after = store.samples()["rows"][1]
        self.assertTrue(answer["region_reviewed"])
        self.assertEqual(answer["region_reviewed_count"], 1)
        self.assertEqual(before["reference"], after["reference"])
        self.assertTrue(after["verified"])
        self.assertEqual(before["ocr_prediction"], after["ocr_prediction"])
        self.assertEqual(after["region_type"], "stamp_overlap")
        with self.assertRaises(ValueError):
            store.save("b", "classify", region_type="auto_correct")

    def test_unreviewed_is_never_silently_declared_printed(self):
        from demo.local_pdf_ocr.quality.zone_audit import verified_region_rows
        got = verified_region_rows(self.samples, self.labels)
        self.assertEqual([x["region_type"] for x in got], ["unreviewed"] * 3)

    def test_candidate_ledger_contains_no_automatic_selection(self):
        from demo.local_pdf_ocr.quality.zone_audit import verified_region_rows
        got = verified_region_rows(
            verified_samples(self.root, min_verified=1), self.labels
        )
        ledger = candidate_ledger(self.root, got)
        self.assertEqual(len(ledger), 1)
        self.assertFalse(ledger[0]["automatic_choice_approved"])
        self.assertTrue(all(x["char_delta"] == -2 for x in ledger[0]["variants"]))
        self.assertTrue(all(x["improves_both_or_ties_wer"] for x in ledger[0]["variants"]))

    def test_stale_prediction_is_rejected(self):
        content = json.loads((self.root / "error_analysis.json").read_text(encoding="utf-8"))
        content["lines"][0]["baseline"] = "another OCR prediction"
        (self.root / "error_analysis.json").write_text(json.dumps(content), encoding="utf-8")
        from demo.local_pdf_ocr.quality.zone_audit import verified_region_rows
        with self.assertRaisesRegex(ValueError, "Stale"):
            candidate_ledger(self.root, verified_region_rows(
                verified_samples(self.root, min_verified=1), self.labels
            ))

    def test_stamp_artifact_exclusion_is_separate_sensitivity_not_baseline(self):
        # One independently classified stamp-artifact crop is excluded only
        # from the separate sensitivity score; all-line metrics remain frozen.
        store = ReviewStore(self.root)
        store.save("b", "classify", region_type="stamp_artifact")
        with patch(
            "demo.local_pdf_ocr.quality.zone_audit.verify_previous_report",
            return_value={"scores": {"baseline": self.old_metrics}},
        ):
            result = build_zone_audit(self.root, min_verified=1)
        summary = result["summary"]
        alt = summary["non_stamp_artifact_sensitivity"]
        self.assertEqual(summary["original_all_line_metrics"], self.old_metrics)
        self.assertEqual(summary["verified_lines"], 3)
        self.assertEqual(alt["retained_lines"], 2)
        self.assertEqual(alt["excluded_verified_stamp_artifacts"], 1)
        self.assertEqual(alt["still_unreviewed_lines"], 2)
        self.assertTrue(alt["not_official_cer"])
        self.assertTrue(alt["not_fully_printed_text"])
        self.assertEqual(
            alt["metrics"]["char_errors"],
            self.old_metrics["char_errors"] - 3,
        )
        self.assertEqual(summary["nontext_verified_labels_need_manual_review"], 1)
        self.assertIn("b", summary["nontext_labels_to_review"])
        self.assertIn("KHÔNG phải chỉ số chính thức", render_html(result))

    def test_summary_keeps_all_line_metrics_and_printed_subset_distinct(self):
        with patch(
            "demo.local_pdf_ocr.quality.zone_audit.verify_previous_report",
            return_value={"scores": {"baseline": self.old_metrics}},
        ):
            result = build_zone_audit(self.root, min_verified=1)
        self.assertEqual(result["summary"]["verified_lines"], 3)
        self.assertEqual(result["summary"]["region_unreviewed_lines"], 3)
        self.assertIsNone(result["summary"]["printed_text_only_metrics"])
        self.assertEqual(result["summary"]["original_all_line_metrics"], self.old_metrics)
        self.assertEqual(result["summary"]["candidate_lines_with_local_improvement"], 1)
        self.assertTrue(result["summary"]["no_automatic_recognition_replacement"])
        self.assertFalse(result["summary"]["merge_approved"])
        markup = render_html(result)
        self.assertIn("Số: RU6/TB-VPCP", markup)
        self.assertIn('src="crops/a.png"', markup)


if __name__ == "__main__":
    unittest.main()

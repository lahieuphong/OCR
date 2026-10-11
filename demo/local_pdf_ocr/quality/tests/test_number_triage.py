"""No-model regression checks for risk flags and source-report integrity."""
import copy
import hashlib
import unittest

from demo.local_pdf_ocr.backend.contract import CHECKPOINT_SHA256
from demo.local_pdf_ocr.quality.number_probe import (
    VARIANTS, summarize_variants, validate_groups,
)
from demo.local_pdf_ocr.quality.number_triage import (
    build_triage, suspicious_flags,
)


def observation(i, *, original, reference, contrast=None, unsharp=None):
    return {
        "id": f"test-{i}",
        "document": f"document{i}.pdf",
        "pdf_sha256": hashlib.sha256(f"document{i}".encode()).hexdigest(),
        "page": 1,
        "reference": reference,
        "ocr_original": original,
        "predictions": {
            "baseline": original,
            "contrast_1p15": original if contrast is None else contrast,
            "unsharp_light": original if unsharp is None else unsharp,
        },
        "auto_replace_approved": False,
    }


def fixture():
    calibration = [
        observation(1, original="Số: 2 1/A", reference="Số: 21/A"),
        observation(2, original="Số: RU6/B", reference="Số: 216/B",
                    contrast="Số: 216/B", unsharp="Số: 216/B"),
        observation(3, original="Số: 738/C", reference="Số: 738/C"),
    ]
    holdout = [
        observation(4, original="Số: 1H9/D", reference="Số: 149/D"),
        observation(5, original="Số: 76 /TT-BXD", reference="Số: 76 /TT-BXD"),
        observation(6, original="Số: 10314/KGVX", reference="Số: 10314/KGVX"),
        observation(7, original="Số: 48/QĐ-TTg", reference="Số: 48/QĐ-TTg"),
        observation(8, original="Số: 324/NQ-CP", reference="Số: 324/NQ-CP"),
    ]
    return {
        "status": "OFFLINE_FIELD_PROBE_NOT_PRODUCTION",
        "model_sha256": CHECKPOINT_SHA256,
        "blind_test_used": False,
        "production_model_modified": False,
        "pdf_ocr_rerun": False,
        "automatic_ocr_replacement": False,
        "merge_approved": False,
        "split": validate_groups(calibration, holdout),
        "calibration": summarize_variants(calibration),
        "holdout": summarize_variants(holdout),
        "all_predicted_lines": {
            "calibration": calibration,
            "holdout": holdout,
        },
    }


class NumberTriageTests(unittest.TestCase):
    def test_flags_only_suspect_numeric_serial_without_auto_fix(self):
        self.assertEqual(suspicious_flags("Số: 1H9 /QĐ", {"baseline": "Số: 1H9 /QĐ"}),
                         ["non_digit_serial"])
        self.assertEqual(suspicious_flags("Số: RU6/B", {"baseline": "Số: RU6/B"}),
                         ["non_digit_serial"])
        self.assertEqual(suspicious_flags("Số: 2 1/A", {"baseline": "Số: 2 1/A"}),
                         ["split_digits"])
        self.assertEqual(suspicious_flags("Số: 76 /TT-BXD",
                                          {"baseline": "Số: 76 /TT-BXD"}), [])
        self.assertEqual(suspicious_flags("Số: 324/NQ-CP",
                                          {"baseline": "Số: 324/NQ-CP"}), [])
        self.assertEqual(
            suspicious_flags("Số: 149/D",
                             {"baseline": "Số: 149/D",
                              "contrast_1p15": "Số: 1H9/D"}),
            ["variant_disagreement"],
        )
        self.assertEqual(suspicious_flags("Căn cứ số 20/2026", {}), [])
        self.assertEqual(suspicious_flags("Số: /TT-BXD", {}), ["empty_serial"])

    def test_synthetic_3_plus_5_error_flags_preserve_every_original(self):
        original = fixture()
        after = build_triage(original)
        self.assertEqual(after["status"], "REVIEW_ONLY_NO_GO_FOR_AUTOMATIC_CORRECTION")
        self.assertFalse(after["automatic_correction_approved"])
        self.assertFalse(after["deployment_approved"])
        self.assertFalse(after["merge_approved"])
        self.assertEqual(after["summary"]["calibration"]["flagged_errors"], 2)
        self.assertEqual(after["summary"]["calibration"]["flagged_correct_lines"], 0)
        self.assertEqual(after["summary"]["holdout"]["flagged_errors"], 1)
        self.assertEqual(after["summary"]["holdout"]["flagged_correct_lines"], 0)
        self.assertEqual(after["summary"]["holdout"]["missed_errors"], 0)
        self.assertEqual(after["summary"]["holdout"]["unflagged_correct_lines"], 4)
        self.assertEqual(after["summary"]["holdout"]["flag_recall_on_selected_verified_crops"], 1.0)
        self.assertEqual([r["ocr_original"] for r in after["rows"]],
                         [r["ocr_original"] for r in
                          original["all_predicted_lines"]["calibration"]
                          + original["all_predicted_lines"]["holdout"]])
        self.assertTrue(all(r["replacement_text"] is None for r in after["rows"]))

    def test_fail_closed_if_source_labels_or_trial_predictions_modified(self):
        for key, value in [
            ("blind_test_used", True), ("merge_approved", True),
            ("automatic_ocr_replacement", True),
            ("model_sha256", "0" * 64),
        ]:
            record = fixture()
            record[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "STOP"):
                build_triage(record)
        record = fixture()
        record["all_predicted_lines"]["holdout"][0]["reference"] = "Số: 1H9/D"
        with self.assertRaisesRegex(ValueError, "metrics"):
            build_triage(record)
        record = fixture()
        record["all_predicted_lines"]["calibration"][1]["predictions"]["contrast_1p15"] = "Số: R16/B"
        with self.assertRaisesRegex(ValueError, "metrics"):
            build_triage(record)
        record = fixture()
        record["all_predicted_lines"]["holdout"][0]["pdf_sha256"] = (
            record["all_predicted_lines"]["calibration"][0]["pdf_sha256"]
        )
        with self.assertRaisesRegex(ValueError, "share PDF content|split"):
            build_triage(record)

    def test_ground_truth_or_doc_name_can_never_drive_flag_function(self):
        raw = "Số: 1H9/D"
        before = suspicious_flags(raw, {"baseline": raw})
        self.assertEqual(before, ["non_digit_serial"])
        record = fixture()
        record["all_predicted_lines"]["holdout"][0]["reference"] = raw
        record["holdout"] = summarize_variants(record["all_predicted_lines"]["holdout"])
        alternative = build_triage(record)
        row = next(x for x in alternative["rows"] if x["id"] == "test-4")
        self.assertTrue(row["needs_human_review"])
        self.assertFalse(row["observed_ocr_error"])
        self.assertIsNone(row["replacement_text"])

    def test_no_holdout_is_allowed_but_never_authorizes_deploy(self):
        record = fixture()
        record["all_predicted_lines"]["holdout"] = []
        record["holdout"] = None
        record["split"] = validate_groups(record["all_predicted_lines"]["calibration"], [])
        result = build_triage(record)
        self.assertEqual(result["summary"]["holdout"]["flagged"], 0)
        self.assertIsNone(result["summary"]["holdout"]["flag_recall_on_selected_verified_crops"])
        self.assertFalse(result["deployment_approved"])


if __name__ == "__main__":
    unittest.main()

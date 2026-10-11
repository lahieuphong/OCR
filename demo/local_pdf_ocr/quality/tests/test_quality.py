"""No PaddlePaddle/ONNX needed; only synthetic data and standard library."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from demo.local_pdf_ocr.quality.benchmark import (
    distance, metrics, verified_samples, transform
)
from demo.local_pdf_ocr.quality.prepare_review import (
    priority, safe_id, selected_lines
)


def write_jsonl(path, data):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in data),
                    encoding="utf-8")


class QualityLabTests(unittest.TestCase):
    def test_distance_and_metrics_preserve_accents_and_punctuation(self):
        self.assertEqual(distance("triển", "triên"), 1)
        self.assertEqual(distance("XIII", "XIIII"), 1)
        self.assertEqual(distance([], []), 0)
        score = metrics([("triển", "triên"), ("XIII", "XIIII"), ("đúng", "đúng")])
        self.assertEqual(score["char_errors"], 2)
        self.assertEqual(score["word_errors"], 2)
        self.assertEqual(score["exact_lines"], 1)

    def test_normalized_nfc_is_stable(self):
        self.assertEqual(metrics([("ấ", "a\u0302\u0301")])["char_errors"], 0)

    def test_no_implicit_ground_truth(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            crop = root / "test.png"
            crop.write_bytes(b"test-image")
            digest = hashlib.sha256(b"test-image").hexdigest()
            manifest = [{"id":"sample", "ocr_prediction":"Công",
                         "crop_path":"test.png", "crop_sha256":digest}]
            labels = [{"id":"sample","crop_sha256":digest,"reference":None,"verified":False}]
            write_jsonl(root / "manifest.jsonl", manifest)
            write_jsonl(root / "labels.jsonl", labels)
            with self.assertRaisesRegex(ValueError,"human-verified"):
                verified_samples(root,min_verified=1)
            labels[0]["reference"] = "Cộng"
            labels[0]["verified"] = True
            write_jsonl(root / "labels.jsonl", labels)
            got = verified_samples(root,min_verified=1)
            self.assertEqual(got[0]["reference"],"Cộng")
            self.assertEqual(got[0]["ocr_prediction"],"Công")
            crop.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError,"changed"):
                verified_samples(root,min_verified=1)

    def test_labels_sha_and_unknown_ids_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "img.png").write_bytes(b"fake")
            digest = hashlib.sha256(b"fake").hexdigest()
            write_jsonl(root / "manifest.jsonl", [
                {"id":"sample","crop_sha256":digest,"crop_path":"img.png"}])
            write_jsonl(root / "labels.jsonl", [
                {"id":"forged","crop_sha256":digest,"reference":"đúng","verified":True}])
            with self.assertRaisesRegex(ValueError,"unknown"):
                verified_samples(root,min_verified=1)
            write_jsonl(root / "labels.jsonl", [
                {"id":"sample","crop_sha256":"0"*64,"reference":"đúng","verified":True}])
            with self.assertRaisesRegex(ValueError,"differs"):
                verified_samples(root,min_verified=1)

    def test_selection_prioritizes_manual_focus_and_flags(self):
        rows=[
            {"line_index":1,"text":"hello"},
            {"line_index":2,"text":"Cổng Văn phòng"},
            {"line_index":3,"text":"XIIII"},
            {"line_index":4,"text":"hello again"},
        ]
        page={"lines":rows, "detection_review":{"flags":[{"source_line_index":2}]}}
        result=selected_lines(page, per_page=2, focus=("XIIII",))
        self.assertEqual([x["line_index"] for x in result],[3,2])
        self.assertEqual([x["line_index"] for x in rows],[1,2,3,4])
        self.assertEqual(safe_id("../signed-id.v1.pdf"),"signed-id_v1")

    def test_unknown_variant_rejected(self):
        with self.assertRaises(ValueError):
            transform(None,"magic-spellcheck")


if __name__ == "__main__":
    unittest.main()

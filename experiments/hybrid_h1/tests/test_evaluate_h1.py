"""Labels v2 references for the A0/H1 comparison (synthetic file)."""
import json
import tempfile
import unittest
from pathlib import Path

from experiments.hybrid_h1.evaluate_h1 import LABELS_V2_SCHEMA, labels_v2_references


class LabelsV2(unittest.TestCase):
    def test_only_verified_lines_with_a_reference_are_used(self):
        rows = [
            {"id": "a", "document": "d.pdf", "page": 1, "line_index": 23, "review": {"status": "verified", "reference": "ý kiến"}},
            {"id": "b", "document": "d.pdf", "page": 3, "line_index": 31, "review": {"status": "uncertain", "reference": None}},
        ]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "labels_v2.json"
            path.write_text(json.dumps({"schema": LABELS_V2_SCHEMA, "labels": rows}, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(labels_v2_references(path), {"d.pdf|1|23": "ý kiến"})
            path.write_text(json.dumps({"schema": "vietdoc_holdout_manual_review_v1", "labels": rows}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not a labels v2"):
                labels_v2_references(path)


if __name__ == "__main__":
    unittest.main()

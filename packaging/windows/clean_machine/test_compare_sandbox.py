"""Tests for compare_sandbox.py on synthetic responses."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_sandbox import compare  # noqa: E402


def write(path: Path, data: dict, bom: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + json.dumps(data).encode("utf-8"))


class CompareSandboxTest(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.mkdtemp())
        self.results, self.ref = base / "results", base / "ref"
        write(self.ref / "a.pdf__vietocr_ocr.json", {"text": "Số 1", "x": 2.0, "elapsed_ms": 5})
        write(self.results / "ocr_installed" / "a.pdf__vietocr_ocr.json", {"text": "Số 1", "x": 2, "elapsed_ms": 9}, bom=True)
        write(self.results / "vn_out" / "ocr_vn_user" / "a.pdf__vietocr_ocr.json", {"text": "Số 1", "x": 2})

    def test_identical_responses_pass(self):
        summary = compare(self.results, self.ref)
        self.assertEqual((summary["result"], summary["compared"], summary["identical"]), ("PASS", 2, 2))

    def test_a_difference_or_a_missing_reference_fails(self):
        write(self.results / "ocr_portable" / "a.pdf__vietocr_ocr.json", {"text": "Số 7", "x": 2})
        write(self.results / "ocr_portable" / "b.png__vietocr_ocr.json", {"text": "x"})
        summary = compare(self.results, self.ref)
        self.assertEqual(summary["result"], "FAIL")
        self.assertIn("ocr_portable/a.pdf__vietocr_ocr.json".replace("/", "\\") if sys.platform == "win32"
                      else "ocr_portable/a.pdf__vietocr_ocr.json", summary["different"])
        self.assertEqual(len(summary["missing_reference"]), 1)

    def test_no_responses_is_not_a_pass(self):
        self.assertEqual(compare(Path(tempfile.mkdtemp()), self.ref)["result"], "FAIL")


if __name__ == "__main__":
    unittest.main()

"""Tests for the comparison rules of check_packaged_ocr.py (no backend is started)."""
import argparse
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_packaged_ocr as check  # noqa: E402


class ComparisonTest(unittest.TestCase):
    def test_only_timing_fields_are_ignored(self):
        a = {"elapsed_ms": 10, "request_elapsed_ms": 12, "pages": [{"lines": [{"text": "Số: 12", "seconds": 1}]}]}
        b = {"elapsed_ms": 99, "request_elapsed_ms": 98, "pages": [{"lines": [{"text": "Số: 12", "seconds": 7}]}]}
        self.assertEqual(check.differences(check.strip_timing(a), check.strip_timing(b)), [])
        b["pages"][0]["lines"][0]["text"] = "Số: 13"
        self.assertEqual(check.differences(check.strip_timing(a), check.strip_timing(b)),
                         ["$.pages[0].lines[0].text: 'Số: 12' != 'Số: 13'"])

    def test_missing_keys_lengths_and_types_are_differences(self):
        self.assertEqual(check.differences({"a": 1}, {"b": 1}), ["$.a: only in this run", "$.b: only in reference"])
        self.assertEqual(check.differences([1, 2], [1]), ["$: 2 items != 1"])
        self.assertEqual(check.differences({"a": 1}, {"a": "1"}), ["$.a: int != str"])

    def test_numbers_compare_by_value_but_booleans_stay_booleans(self):
        self.assertEqual(check.differences({"x": 356}, {"x": 356.0}), [])
        self.assertEqual(check.differences({"x": 356}, {"x": 356.5}), ["$.x: 356 != 356.5"])
        self.assertEqual(check.differences({"x": True}, {"x": 1}), ["$.x: bool != int"])

    def test_each_file_and_mode_has_its_own_response_file(self):
        names = {check.label(Path(f"page.{ext}"), mode) for ext in ("png", "jpg", "pdf") for mode in ("vietocr_ocr", "metadata_fast")}
        self.assertEqual(len(names), 6)

    def test_document_arguments_name_an_existing_file_and_a_mode(self):
        path = Path(tempfile.mkdtemp(), "văn bản 1.pdf")
        path.write_bytes(b"%PDF-1.7")
        self.assertEqual(check.document(f"{path}=metadata_fast"), (path, "metadata_fast"))
        for value in (f"{path}=fast", f"{path}", f"{path.with_name('missing.pdf')}=native_text"):
            with self.assertRaises(argparse.ArgumentTypeError):
                check.document(value)


if __name__ == "__main__":
    unittest.main()

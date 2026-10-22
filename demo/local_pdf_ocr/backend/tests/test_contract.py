"""Tests requiring only Python standard library, not model downloads."""
import json
import tempfile
import unittest
from pathlib import Path

from demo.local_pdf_ocr.backend.contract import (
    DemoConfigurationError, decode_ids, validate_upload, verify_frozen_onnx,
)


class ContractTests(unittest.TestCase):
    def test_decode_unicode_and_eos(self):
        self.assertEqual(decode_ids([1, 4, 5, 2, 6], "ấđớ"), "ấđ")
        self.assertEqual(decode_ids([1, 4, 5], "ấđớ"), "ấđ")
        self.assertEqual(decode_ids([1, 0, 3, 2], "ấđớ"), "<pad>*")

    def test_upload_magic(self):
        self.assertEqual(validate_upload("scan.PDF", b"%PDF-1.7\n"), ".pdf")
        self.assertEqual(validate_upload("scan.png", b"\x89PNG\r\n\x1a\nabc"), ".png")
        with self.assertRaises(ValueError):
            validate_upload("fake.pdf", b"not pdf")
        with self.assertRaises(ValueError):
            validate_upload("scan.exe", b"%PDF-1.7")
        with self.assertRaises(ValueError):
            validate_upload("scan.jpg", b"\x89PNG\r\n\x1a\n")

    def test_missing_parity_report_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(DemoConfigurationError):
                verify_frozen_onnx(Path(directory), require_weights=False)


if __name__ == "__main__":
    unittest.main()

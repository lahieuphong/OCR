"""Model-free tests: explicit PDF embedded text vs independent OCR.

These tests synthesize small PDFs in memory. Never touch frozen training or
blind-test examples, PaddleOCR, checkpoint weights, or inference downloads.
"""
from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

from demo.local_pdf_ocr.backend.text_layer import extract_pdf_text


def pdf_with_text() -> bytes:
    import fitz

    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_text((70, 60), "Government notice - Decision XIII +07:00")
    page.insert_text((70, 650), "Recipients:\n- Agency A\n- Agency B")
    page.insert_text((330, 650), "SIGNATURE\nDirector")
    data = pdf.tobytes()
    pdf.close()
    return data


class PdfTextLayerTests(unittest.TestCase):
    def test_preserves_text_and_separates_footer_blocks(self):
        result = extract_pdf_text(pdf_with_text(), "government.pdf")
        self.assertEqual(result["method"], "native_text")
        self.assertEqual(result["engine"], "PyMuPDF")
        self.assertIsNone(result["model"])
        self.assertFalse(result["used_ocr"])
        self.assertEqual(result["page_count"], 1)
        self.assertGreater(result["line_count"], 2)
        self.assertIn("Decision XIII +07:00", result["text"])
        self.assertIn("- Agency A", result["text"])
        self.assertIn("SIGNATURE", result["text"])
        self.assertLess(result["text"].index("Agency B"), result["text"].index("SIGNATURE"))
        self.assertEqual(result["pages"][0]["reading_order"], "pdf_content_stream_blocks")
        self.assertEqual(result["pages"][0]["coordinate_system"], "pdf_points")
        self.assertIsNone(result["decoder_limit_hits"])
        self.assertFalse(result["deployment_approved"])

    def test_scanned_pdf_refuses_silent_ocr_fallback(self):
        import fitz

        doc = fitz.open()
        doc.new_page()
        scanned = doc.tobytes()
        doc.close()
        with self.assertRaisesRegex(ValueError, "không có lớp văn bản"):
            extract_pdf_text(scanned, "scan.pdf")

    def test_rejects_image_in_native_text_mode(self):
        with self.assertRaisesRegex(ValueError, "chỉ hỗ trợ"):
            extract_pdf_text(b"\x89PNG\r\n\x1a\nbinary", "pic.png")

    def test_mixed_pdf_keeps_empty_pages_visible(self):
        import fitz

        doc = fitz.open()
        doc.new_page().insert_text((30, 30), "Page one")
        doc.new_page()
        mixed = doc.tobytes()
        doc.close()
        result = extract_pdf_text(mixed, "mixed.pdf")
        self.assertEqual(result["pages_without_text"], [2])
        self.assertEqual(result["pages"][1]["text"], "")


class ApiModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_mode_never_initializes_ocr(self):
        from fastapi import UploadFile
        from demo.local_pdf_ocr.backend import app as service

        upload = UploadFile(filename="notice.pdf", file=io.BytesIO(pdf_with_text()))
        with patch.object(service, "get_engine", side_effect=AssertionError("OCR must not run")):
            response = await service.ocr(file=upload, mode="native_text")
        result = json.loads(response.body)
        self.assertEqual(result["method"], "native_text")
        self.assertFalse(result["used_ocr"])

    async def test_ocr_mode_never_reads_pdf_text_layer(self):
        from fastapi import UploadFile
        from demo.local_pdf_ocr.backend import app as service

        class FakeEngine:
            def process(self, payload, filename):
                return {"method": "vietocr_ocr", "used_ocr": True, "pages": [],
                        "text": "recognized from crops", "filename": filename}
        upload = UploadFile(filename="notice.pdf", file=io.BytesIO(pdf_with_text()))
        with patch.object(service, "extract_pdf_text", side_effect=AssertionError("PDF text must not be read")), \
             patch.object(service, "get_engine", return_value=FakeEngine()):
            response = await service.ocr(file=upload, mode="vietocr_ocr")
        result = json.loads(response.body)
        self.assertEqual(result["method"], "vietocr_ocr")
        self.assertTrue(result["used_ocr"])

    async def test_mode_required_from_allowlist(self):
        from fastapi import UploadFile, HTTPException
        from demo.local_pdf_ocr.backend import app as service

        upload = UploadFile(filename="notice.pdf", file=io.BytesIO(pdf_with_text()))
        with self.assertRaises(HTTPException) as context:
            await service.ocr(file=upload, mode="auto")
        self.assertEqual(context.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()

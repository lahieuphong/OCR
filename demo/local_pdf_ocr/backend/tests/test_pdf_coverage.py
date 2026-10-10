"""Synthetic tests for scan-dominant signed PDFs. No external OCR."""
import io
import unittest

from demo.local_pdf_ocr.backend.pdf_coverage import native_page_status


class PdfCoverageTests(unittest.TestCase):
    def test_text_only_pdf_is_complete(self):
        import fitz
        d=fitz.open()
        page=d.new_page(width=600,height=840)
        page.insert_text((60,100),"Document paragraph")
        status=native_page_status(page,1)
        self.assertFalse(status["scan_dominant"])
        self.assertFalse(status["needs_ocr_for_page_content"])
        d.close()

    def test_signature_only_text_over_full_page_scan_requires_ocr(self):
        import fitz
        from PIL import Image

        d=fitz.open()
        page=d.new_page(width=600,height=840)
        bitmap=Image.new("RGB",(60,84),"white")
        binary=io.BytesIO()
        bitmap.save(binary,format="PNG")
        page.insert_image(page.rect,stream=binary.getvalue())
        page.insert_text((180,20),"Signature audit")
        status=native_page_status(page,1)
        self.assertEqual(status["max_raster_page_coverage"],1.0)
        self.assertTrue(status["scan_dominant"])
        self.assertTrue(status["needs_ocr_for_page_content"])
        d.close()

    def test_page_with_no_text_requires_ocr(self):
        import fitz
        d=fitz.open()
        page=d.new_page()
        self.assertTrue(native_page_status(page,0)["needs_ocr_for_page_content"])
        d.close()


if __name__=="__main__":
    unittest.main()

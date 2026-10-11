"""Model-free preview tests: pixels from original PDF, no OCR model inference."""
from __future__ import annotations

import io
import json
import unittest

from PIL import Image

from demo.local_pdf_ocr.backend.number_review_preview import create_review_preview


def png_source():
    out = io.BytesIO()
    Image.new("RGB", (300, 160), "white").save(out, "PNG")
    return out.getvalue()


class NumberPreviewTests(unittest.TestCase):
    def test_crop_returns_original_pixels_without_changing_ocr(self):
        content = png_source()
        quad = json.dumps([[60, 40], [230, 40], [230, 75], [60, 75]])
        image = create_review_preview(
            content, "original.png", page=1, width=300, height=160,
            polygon_json=quad,
        )
        with Image.open(io.BytesIO(image)) as cropped:
            self.assertEqual(cropped.format, "PNG")
            self.assertEqual(cropped.size, (194, 59))
            self.assertEqual(cropped.getpixel((10, 10)), (255, 255, 255))

    def test_mismatched_dimensions_and_unsafe_polygon_fail(self):
        content = png_source()
        quad = json.dumps([[60, 40], [230, 40], [230, 75], [60, 75]])
        with self.assertRaisesRegex(ValueError, "differs"):
            create_review_preview(content, "original.png",
                                  page=1, width=299, height=160, polygon_json=quad)
        with self.assertRaisesRegex(ValueError, "outside"):
            create_review_preview(content, "original.png",
                                  page=1, width=300, height=160,
                                  polygon_json=json.dumps([[-2, 40], [230, 40], [230, 75], [-2, 75]]))
        with self.assertRaisesRegex(ValueError, "page"):
            create_review_preview(content, "original.png",
                                  page=2, width=300, height=160, polygon_json=quad)
        with self.assertRaisesRegex(ValueError, "coordinates"):
            create_review_preview(content, "original.png",
                                  page=1, width=300, height=160,
                                  polygon_json=json.dumps([[20, True], [70, 40], [70, 75], [20, 75]]))

    def test_original_pdf_crop_uses_same_page_geometry(self):
        try:
            import fitz
        except ImportError:
            self.skipTest("PyMuPDF not installed")
        pdf=fitz.open()
        page=pdf.new_page(width=300, height=160)
        page.insert_text((60, 48), "Số: 149/QĐ")
        data=pdf.tobytes()
        pdf.close()
        # This is a 2x render, same as engine.iter_images and crop helper.
        result=create_review_preview(
            data, "scan.pdf", page=1, width=600, height=320,
            polygon_json=json.dumps([[95, 62], [320, 62], [320, 112], [95, 112]]),
        )
        with Image.open(io.BytesIO(result)) as img:
            self.assertEqual(img.format, "PNG")
            self.assertGreater(img.width, 210)

    def test_invalid_text_or_pdf_fails_without_ocr_fallback(self):
        with self.assertRaises(ValueError):
            create_review_preview(b"broken", "broken.pdf", page=1, width=300,
                                  height=160,polygon_json=json.dumps([[10, 10], [20, 10], [20, 20], [10, 20]]))


class PreviewApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_preview_api_returns_png_and_refuses_mismatched_source(self):
        from fastapi import HTTPException, UploadFile
        from demo.local_pdf_ocr.backend import app as service

        quad = json.dumps([[60, 40], [230, 40], [230, 75], [60, 75]])
        image = await service.review_crop(
            file=UploadFile(filename="image.png", file=io.BytesIO(png_source())),
            page=1, width=300, height=160, polygon=quad,
        )
        self.assertEqual(image.media_type, "image/png")
        self.assertTrue(image.body.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(image.headers["cache-control"], "no-store")
        with self.assertRaises(HTTPException) as ctx:
            await service.review_crop(
                file=UploadFile(filename="image.png", file=io.BytesIO(png_source())),
                page=1, width=301, height=160, polygon=quad,
            )
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()

"""Model-free integration tests for the local OCR demo.

These NEVER read training/blind files or download PaddleOCR models. The fake
detector + recognizer checks page plumbing, ordering, response and unicode.
"""
from __future__ import annotations

import io
import unittest

from demo.local_pdf_ocr.backend.engine import (
    LocalOcrEngine, iter_images, resize_width, sort_detected_polygons, vietocr_tensor,
)


class EngineTests(unittest.TestCase):
    def test_resize_rounds_and_caps_as_pinned(self):
        self.assertEqual(resize_width(100, 32), 100)
        self.assertEqual(resize_width(101, 32), 110)
        self.assertEqual(resize_width(1, 32), 32)
        self.assertEqual(resize_width(2000, 32), 1024)
        with self.assertRaises(ValueError):
            resize_width(0, 20)

    def test_preprocess_white_rgb_tensor(self):
        import numpy as np
        from PIL import Image
        metadata = {
            "image_height": 32,
            "image_min_width": 32,
            "image_max_width": 1024,
        }
        tensor = vietocr_tensor(Image.new("RGB", (101, 32), "white"), metadata)
        self.assertEqual(tensor.shape, (1, 3, 32, 110))
        self.assertEqual(tensor.dtype, np.float32)
        self.assertTrue(np.all(tensor == 1))

    def test_sort_simple_column(self):
        boxes = [
            [[0, 80], [20, 80], [20, 90], [0, 90]],
            [[0, 10], [20, 10], [20, 20], [0, 20]],
        ]
        self.assertEqual(sort_detected_polygons(boxes), boxes[::-1])

    def test_local_image_e2e_with_stubbed_models(self):
        from PIL import Image
        class FakeDetector:
            def detect_and_crop(self, page_image):
                self_image = Image.new("RGB", (150, 32), "white")
                yield [[0, 0], [149, 0], [149, 31], [0, 31]], self_image

        class FakeRecognizer:
            def predict(self, img):
                return "Chuẩn tiếng Việt – triển khai", False

        engine = LocalOcrEngine.__new__(LocalOcrEngine)
        engine.detector = FakeDetector()
        engine.recognizer = FakeRecognizer()
        engine.checkpoint_sha256 = "stub"

        data = io.BytesIO()
        Image.new("RGB", (260, 120), "white").save(data, format="PNG")
        result = engine.process(data.getvalue(), "demo.png")
        self.assertEqual(result["page_count"], 1)
        self.assertEqual(result["line_count"], 1)
        self.assertEqual(result["decoder_limit_hits"], 0)
        self.assertEqual(result["text"], "Chuẩn tiếng Việt – triển khai")
        self.assertFalse(result["deployment_approved"])
        self.assertEqual(result["pages"][0]["lines"][0]["line_index"], 1)

    def test_pdf_4_pages_rejected_if_more_than_max(self):
        try:
            import fitz
        except ImportError:
            self.skipTest("PyMuPDF not installed")
        pdf = fitz.open()
        for _ in range(7):
            pdf.new_page()
        document = pdf.tobytes()
        pdf.close()
        with self.assertRaisesRegex(ValueError, "tối đa"):
            list(iter_images(document, ".pdf"))


if __name__ == "__main__":
    unittest.main()

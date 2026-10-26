"""Synthetic, model-free checks of original-document preview boundaries."""
from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from demo.local_pdf_ocr.backend.contract import MAX_UPLOAD_BYTES
from demo.local_pdf_ocr.backend.number_review_preview import (
    parse_preview_polygon, render_number_review_preview,
)


QUAD = [[20, 20], [80, 20], [80, 40], [20, 40]]


def image_bytes(size=(120, 80), *, jpeg=False, orientation=None):
    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).rectangle((20, 20, 79, 39), fill="blue")
    output = io.BytesIO()
    kwargs = {}
    if orientation is not None:
        exif = Image.Exif()
        exif[274] = orientation
        kwargs["exif"] = exif
    image.save(output, format="JPEG" if jpeg else "PNG", **kwargs)
    image.close()
    return output.getvalue()


class PreviewTests(unittest.TestCase):
    def render(self, payload=None, filename="synthetic.png", **kwargs):
        arguments = dict(page=1, polygon=QUAD, render_width=120, render_height=80)
        arguments.update(kwargs)
        return render_number_review_preview(image_bytes() if payload is None else payload, filename, **arguments)

    def test_crop_preserves_original_pixels_and_never_initializes_models(self):
        with patch("demo.local_pdf_ocr.backend.engine.LocalOcrEngine.__init__", side_effect=AssertionError("No models")):
            result = self.render()
        self.assertTrue(result.startswith(b"\x89PNG\r\n\x1a\n"))
        with Image.open(io.BytesIO(result)) as crop:
            self.assertEqual(crop.size, (84, 44))
            self.assertEqual(crop.getpixel((12, 12)), (0, 0, 255))
            self.assertEqual(crop.getpixel((0, 0)), (255, 255, 255))

    def test_edge_context_is_clamped_without_scaling(self):
        result = self.render(polygon=[[0, 0], [30, 0], [30, 20], [0, 20]])
        with Image.open(io.BytesIO(result)) as crop:
            self.assertEqual(crop.size, (42, 32))

    def test_pdf_uses_ocr_render_dimensions_and_requested_page(self):
        import fitz
        with fitz.open() as pdf:
            pdf.new_page(width=60, height=40)
            second = pdf.new_page(width=60, height=40)
            second.draw_rect(fitz.Rect(10, 10, 40, 20), color=(0, 0, 1), fill=(0, 0, 1))
            payload = pdf.tobytes()
        result = self.render(payload, "synthetic.pdf", page=2)
        with Image.open(io.BytesIO(result)) as crop:
            self.assertEqual(crop.size, (84, 44))
            self.assertEqual(crop.getpixel((20, 20)), (0, 0, 255))
        with self.assertRaises(ValueError):
            self.render(payload, "synthetic.pdf", page=3)

    def test_exif_orientation_matches_ocr_upright_image(self):
        payload = image_bytes((80, 120), jpeg=True, orientation=6)
        self.assertTrue(self.render(payload, "synthetic.jpg").startswith(b"\x89PNG"))
        with self.assertRaisesRegex(ValueError, "không khớp"):
            self.render(payload, "synthetic.jpg", render_width=80, render_height=120)

    def test_invalid_page_and_dimension_types_rejected(self):
        for kwargs in [dict(page=0), dict(page=7), dict(page=True), dict(page=1.0),
                       dict(page=2), dict(render_width=True), dict(render_height=0),
                       dict(render_width=120.0), dict(render_width=12000000)]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.render(**kwargs)

    def test_wrong_dimensions_or_file_header_rejected(self):
        with self.assertRaisesRegex(ValueError, "không khớp"):
            self.render(render_width=121)
        with self.assertRaises(ValueError):
            self.render(b"not a PNG")
        with self.assertRaises(ValueError):
            self.render(filename="synthetic.txt")
        with self.assertRaises(ValueError):
            self.render(b"\x89PNG\r\n\x1a\n" + b"x" * MAX_UPLOAD_BYTES)

    def test_invalid_polygons_rejected_before_rendering(self):
        invalid = [None, [], [[0, 0]] * 4,
                   [[-1, 1], [20, 1], [20, 20], [-1, 20]],
                   [[0, 0], [121, 0], [121, 20], [0, 20]],
                   [[0, 0], [20, 20], [0, 20], [20, 0]],
                   [[0, 0], [20, 0], [20, float("nan")], [0, 20]],
                   [[True, 0], [20, 0], [20, 20], [0, 20]],
                   [[0, 0], [20, 0], [20, float("inf")], [0, 20]],
                   [[0, 0], [10 ** 400, 0], [20, 20], [0, 20]],
                   [[0, 0], [20, 0], [5, 5], [0, 20]]]
        for polygon in invalid:
            with self.subTest(polygon=polygon), self.assertRaises(ValueError):
                self.render(polygon=polygon)

    def test_parser_rejects_invalid_json_and_large_fields(self):
        self.assertEqual(parse_preview_polygon(json.dumps(QUAD)), QUAD)
        for value in [None, "{", "null", "[NaN]", " " * 2049, "[" * 2048, "\ud800"]:
            with self.subTest(value=str(value)[:30]), self.assertRaises(ValueError):
                parse_preview_polygon(value)

    def test_large_preview_is_refused(self):
        with self.assertRaisesRegex(ValueError, "quá lớn"):
            self.render(image_bytes((1800, 1800)), render_width=1800, render_height=1800,
                        polygon=[[0, 0], [1700, 0], [1700, 1700], [0, 1700]])

    def test_oversized_image_and_seven_page_pdf_refused(self):
        with self.assertRaises(ValueError):
            self.render(image_bytes((12001, 1000)))
        import fitz
        with fitz.open() as pdf:
            for _ in range(7):
                pdf.new_page(width=60, height=40)
            payload = pdf.tobytes()
        with self.assertRaisesRegex(ValueError, "tối đa"):
            self.render(payload, "synthetic.pdf")


if __name__ == "__main__":
    unittest.main()

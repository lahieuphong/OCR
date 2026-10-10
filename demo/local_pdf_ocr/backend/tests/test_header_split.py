"""Model-free tests for an opt-in split: never require PaddleOCR/VietOCR."""
from __future__ import annotations

import unittest

from PIL import Image, ImageDraw

from demo.local_pdf_ocr.backend.header_split import propose_header_split


def example_image(with_gutter=True):
    image = Image.new("RGB", (1200, 1700), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((175, 149, 423 if with_gutter else 1060, 175), fill="black")
    if with_gutter:
        draw.rectangle((521, 149, 1057, 175), fill="black")
    polygon = [[170, 144], [1066, 146], [1066, 184], [170, 182]]
    return image, polygon


class HeaderSplitTests(unittest.TestCase):
    def test_uses_real_white_gutter_and_preserves_quad_outline(self):
        image, quad = example_image()
        proposal = propose_header_split(image, quad)
        self.assertIsNotNone(proposal)
        self.assertEqual(len(proposal["polygons"]), 2)
        left, right = proposal["polygons"]
        self.assertGreater(proposal["audit"]["gap_px"], 18)
        self.assertEqual(left[0], quad[0])
        self.assertEqual(left[-1], quad[-1])
        self.assertEqual(right[1], quad[1])
        self.assertEqual(right[2], quad[2])
        self.assertEqual(left[1], right[0])
        self.assertEqual(left[2], right[3])
        self.assertTrue(423 < proposal["audit"]["gap_x"] < 521)

    def test_no_gutter_falls_back(self):
        image, quad = example_image(with_gutter=False)
        self.assertIsNone(propose_header_split(image, quad))

    def test_never_changes_pages_after_first(self):
        image, quad = example_image()
        self.assertIsNone(propose_header_split(image, quad, page_number=2))

    def test_never_splits_body_lines(self):
        image, quad = example_image()
        quad = [[x, y+300] for x, y in quad]
        self.assertIsNone(propose_header_split(image, quad))

    def test_fails_closed_for_invalid_or_rotated_region(self):
        image, quad = example_image()
        self.assertIsNone(propose_header_split(image, [[0, 0]]))
        rotated = [[170, 144], [1066, 195], [1066, 225], [170, 182]]
        self.assertIsNone(propose_header_split(image, rotated))

    def test_source_array_not_mutated(self):
        image, quad = example_image()
        original = [list(p) for p in quad]
        _ = propose_header_split(image, quad)
        self.assertEqual(original, quad)


if __name__ == "__main__":
    unittest.main()

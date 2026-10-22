"""Geometry-only unit/regression tests for the OCR two-column footer.

Synthetic lines are based on a page with one long body ending around
y=1228, followed by a left-side recipient list and a separate right-side
signature. No source PDF, private text, training or blind dataset is stored.
"""
from __future__ import annotations

import unittest

from demo.local_pdf_ocr.backend.ocr_layout import reorder_split_footer


def line(index: int, box: tuple[int, int, int, int], text: str | None = None) -> dict:
    x0, y0, x1, y1 = box
    return {
        "line_index": index,
        "polygon": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
        "text": text if text is not None else f"original-token-{index:02d}",
        "hit_decoder_limit": False,
    }


def example_page():
    # Wide body line closes at y=1228; footer occupies x < 530 and x > 640.
    return [
        line(1, (170, 1130, 1075, 1160)),
        line(2, (236, 1195, 1074, 1228)),
        line(3, (167, 1230, 298, 1261)),  # closing paragraph line
        line(4, (640, 1291, 1049, 1321)),  # right title
        line(5, (177, 1293, 285, 1319)),   # left title
        line(6, (177, 1321, 280, 1345)),   # left entry
        line(7, (728, 1324, 968, 1354)),  # right title continuation
        line(8, (177, 1345, 489, 1370)),
        line(9, (179, 1372, 494, 1396)),
        line(10, (177, 1398, 461, 1423)),
        line(11, (179, 1424, 409, 1444)),
        line(12, (177, 1445, 507, 1472)),
        line(13, (188, 1475, 526, 1495)),
        line(14, (179, 1500, 342, 1524)),
        line(15, (730, 1552, 961, 1593)),  # signer name
    ]


class OcrFooterLayoutTests(unittest.TestCase):
    def test_split_footer_groups_columns_without_modifying_recognition(self):
        original = example_page()
        ordered, decision = reorder_split_footer(original, 1191, 1684)
        self.assertTrue(decision["modified"])
        self.assertEqual(decision["left_line_count"], 10)
        self.assertEqual(decision["right_line_count"], 3)
        self.assertEqual(decision["anchor_source_line_index"], 2)
        self.assertEqual(
            [row["source_line_index"] for row in ordered],
            [1, 2, 3, 5, 6, 8, 9, 10, 11, 12, 13, 14, 4, 7, 15],
        )
        self.assertEqual([row["line_index"] for row in ordered], list(range(1, 16)))
        self.assertEqual(len(ordered), len(original))
        self.assertEqual(
            {i["source_line_index"]: (i["text"], i["polygon"], i["hit_decoder_limit"])
             for i in ordered},
            {i["line_index"]: (i["text"], i["polygon"], i["hit_decoder_limit"])
             for i in original},
        )
        self.assertNotIn("source_line_index", original[3])  # input untouched

    def test_no_wide_anchor_is_left_unchanged(self):
        rows = example_page()[2:]
        ordered, info = reorder_split_footer(rows, 1191, 1684)
        self.assertFalse(info["modified"])
        self.assertEqual([r["line_index"] for r in ordered], [r["line_index"] for r in rows])

    def test_region_too_high_is_left_unchanged(self):
        rows = example_page()
        for item in rows:
            item["polygon"] = [[x, y-580] for x, y in item["polygon"]]
        _ordered, info = reorder_split_footer(rows, 1191, 1684)
        self.assertFalse(info["modified"])

    def test_overlapping_columns_are_not_reordered(self):
        rows = example_page()
        # Right-hand items overlap the left-hand footer horizontal extent.
        for index in (3, 6, 14):
            rows[index]["polygon"] = [[x-225, y] for x, y in rows[index]["polygon"]]
        ordered, info = reorder_split_footer(rows, 1191, 1684)
        self.assertFalse(info["modified"])
        self.assertEqual([r["line_index"] for r in ordered], list(range(1, 16)))

    def test_one_right_line_is_not_enough(self):
        rows = [r for r in example_page() if r["line_index"] not in (7, 15)]
        _ordered, info = reorder_split_footer(rows, 1191, 1684)
        self.assertFalse(info["modified"])

    def test_absent_or_invalid_page(self):
        self.assertEqual(reorder_split_footer([], 1191, 1684)[0], [])
        with self.assertRaises(ValueError):
            reorder_split_footer([], 0, 1684)

    def test_unicode_text_is_not_modified(self):
        rows = example_page()
        rows[3]["text"] = "BÔ TRƯỞNG - khóa XIIII / 407:00"
        rows[4]["text"] = "Nơi nhận: Ớ Ệ"
        ordered, info = reorder_split_footer(rows, 1191, 1684)
        self.assertTrue(info["modified"])
        self.assertIn("BÔ TRƯỞNG - khóa XIIII / 407:00",
                      [r["text"] for r in ordered])
        self.assertIn("Nơi nhận: Ớ Ệ", [r["text"] for r in ordered])


if __name__ == "__main__":
    unittest.main()

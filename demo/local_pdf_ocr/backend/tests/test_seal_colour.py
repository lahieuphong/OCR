"""Seal colour from pixels: synthetic, model-free contracts, not an accuracy score."""
import io
import json
import unittest
from unittest.mock import patch

import pymupdf
from PIL import Image, ImageDraw

from demo.local_pdf_ocr.backend import app as api
from demo.local_pdf_ocr.backend import seal_colour as seal
from test_metadata_fast import header, pdf_bytes
from test_review_api import request

MM = 72 / 25.4
RED = (.85, .1, .1)


def pdf_with(pages=1, draw=None, grey_scan_pages=()):
    """A4 pages; draw(page_index, page) adds marks, grey_scan_pages get a full-page greyscale image."""
    pdf = pymupdf.open()
    for index in range(pages):
        page = pdf.new_page(width=595, height=842)
        if index in grey_scan_pages:
            scan = Image.new("L", (827, 1170), 255)
            ImageDraw.Draw(scan).ellipse((500, 800, 650, 950), outline=60, width=6)  # a seal, but grey
            target = io.BytesIO(); scan.save(target, "PNG")
            page.insert_image(page.rect, stream=target.getvalue())
        page.insert_text((60, 80), "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", fontsize=10)
        if draw:
            draw(index, page)
    data = pdf.tobytes()
    pdf.close()
    return data


def ring(page, diameter_mm=40, centre=(400, 650)):
    page.draw_circle(centre, diameter_mm * MM / 2, color=RED, width=3)
    page.insert_text((centre[0] - 40, centre[1]), "ỦY BAN NHÂN DÂN", fontsize=7, color=RED)


class SealColourTests(unittest.TestCase):
    def test_finds_a_round_red_seal_searching_from_the_last_page(self):
        result = seal.find_seal(pdf_with(4, lambda i, page: ring(page) if i == 1 else None), ".pdf")
        self.assertEqual((result["reason"], result["colour"], result["page"]), ("found", "red", 2))
        self.assertEqual(result["pages_checked"], [4, 3, 2])
        self.assertTrue(all(36 <= size <= 44 for size in result["size_mm"]))
        self.assertTrue(.68 <= result["round_fill"] <= .88)

    def test_rectangular_red_stamp_and_small_emblem_are_not_seals(self):
        def marks(_index, page):
            page.draw_rect(pymupdf.Rect(60, 400, 60 + 40 * MM, 400 + 36 * MM), color=RED, fill=RED)  # "HỎA TỐC"-like box
            ring(page, diameter_mm=10, centre=(450, 120))                                         # e-signature emblem
            ring(page, diameter_mm=80, centre=(300, 600))                                         # too large
        result = seal.find_seal(pdf_with(1, marks), ".pdf")
        self.assertEqual((result["reason"], result["colour"]), ("not_found", None))
        self.assertNotIn("page", result)

    def test_greyscale_scan_is_black_and_white_even_with_coloured_portal_text(self):
        def portal(_index, page):
            page.insert_text((200, 30), "Người ký: CỔNG THÔNG TIN ĐIỆN TỬ", fontsize=8, color=(0, 0, .8))
            page.insert_text((200, 42), "Cơ quan: VĂN PHÒNG", fontsize=8, color=RED)
        result = seal.find_seal(pdf_with(3, portal, grey_scan_pages={0, 1, 2}), ".pdf")
        self.assertEqual((result["reason"], result["colour"]), ("black_and_white", None))
        self.assertEqual((result["pages_checked"], result["greyscale_pages"]), ([3, 2, 1], 3))

    def test_digital_page_without_seal_is_not_called_black_and_white(self):
        result = seal.find_seal(pdf_with(2, grey_scan_pages={0}), ".pdf")
        self.assertEqual((result["reason"], result["greyscale_pages"]), ("not_found", 1))

    def test_long_documents_check_the_last_pages_then_the_first(self):
        self.assertEqual(seal.page_order(3), [2, 1, 0])
        order = seal.page_order(100)
        self.assertEqual(order[:3], [99, 98, 97])
        self.assertEqual(len(order), seal.TAIL_PAGES + seal.HEAD_PAGES)
        self.assertEqual(order[seal.TAIL_PAGES:seal.TAIL_PAGES + 2], [0, 1])
        self.assertEqual(len(seal.page_order(25)), 25)
        self.assertEqual(sorted(seal.page_order(25)), list(range(25)))

    def test_images_are_taken_as_a4_pages(self):
        image = Image.new("RGB", (1240, 1754), "white")
        draw = ImageDraw.Draw(image)
        draw.ellipse((700, 1200, 700 + 236, 1200 + 236), outline=(215, 30, 30), width=8)  # 236 px of 1240 ~ 40 mm
        target = io.BytesIO(); image.save(target, "PNG")
        result = seal.find_seal(target.getvalue(), ".png")
        self.assertEqual((result["reason"], result["page"]), ("found", 1))
        grey = io.BytesIO(); image.convert("L").save(grey, "PNG")
        self.assertEqual(seal.find_seal(grey.getvalue(), ".png")["reason"], "black_and_white")


class SealApiTests(unittest.TestCase):
    def test_every_mode_result_carries_the_seal_check(self):
        payload = pdf_bytes(header())
        status, _, body = request("/api/ocr", {"mode": "native_text"}, "native.pdf", payload)
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["seal"]["method"], seal.METHOD)

    def test_a_failing_seal_check_never_fails_the_text_result(self):
        with patch.object(api, "find_seal", side_effect=RuntimeError("renderer crashed")), \
             self.assertLogs("local_pdf_ocr", "ERROR"):
            status, _, body = request("/api/ocr", {"mode": "native_text"}, "native.pdf", pdf_bytes(header()))
        self.assertEqual(status, 200, body)
        result = json.loads(body)
        self.assertEqual((result["seal"]["reason"], result["seal"]["colour"]), ("error", None))
        self.assertIn("CHÍNH PHỦ", result["text"])


if __name__ == "__main__":
    unittest.main()

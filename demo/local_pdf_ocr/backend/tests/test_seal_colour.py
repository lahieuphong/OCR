"""Seal colour from pixels: synthetic, model-free contracts, not an accuracy score."""
import io
import json
import math
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
YELLOW = (1, .85, 0)
BLUE = (.1, .1, .8)


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


def emblem(page, diameter_mm=34, centre=(300, 200)):
    """A printed national emblem, as on a form's cover in an appendix: a red disc with a yellow star and a yellow
    wreath, two inks. Drawn, not copied from any document."""
    radius = diameter_mm * MM / 2
    page.draw_circle(centre, radius, color=RED, fill=RED)
    page.draw_circle(centre, radius * .85, color=YELLOW, width=radius * .18)
    points = [(centre[0] + r * math.sin(k * math.pi / 5), centre[1] - r * math.cos(k * math.pi / 5))
              for k, r in ((k, radius * (.55 if k % 2 == 0 else .22)) for k in range(10))]
    page.draw_polyline(points + points[:1], color=YELLOW, fill=YELLOW, closePath=True)


class SealColourTests(unittest.TestCase):
    def test_finds_a_round_red_seal_searching_from_the_last_page(self):
        result = seal.find_seal(pdf_with(4, lambda i, page: ring(page) if i == 1 else None), ".pdf")
        self.assertEqual((result["reason"], result["colour"], result["page"]), ("found", "red", 2))
        self.assertEqual(result["pages_checked"], [4, 3, 2])
        self.assertTrue(all(36 <= size <= 44 for size in result["size_mm"]))
        self.assertTrue(.68 <= result["round_fill"] <= .88)

    def test_red_mark_pages_lists_seal_pages_in_search_order_up_to_the_limit(self):
        # Round 6: where a scanned consolidated text was stamped (its authentication block sits above the seal).
        payload = pdf_with(6, lambda i, page: ring(page) if i in (1, 2, 4) else None)
        pages = seal.red_mark_pages(payload, 2)
        self.assertEqual([mark["page"] for mark in pages], [5, 3])
        top = pages[0]["box"][1]
        self.assertAlmostEqual(top, (650 - 20 * MM) / 842, delta=.02)
        self.assertEqual([mark["page"] for mark in seal.red_mark_pages(payload, 5)], [5, 3, 2])
        self.assertEqual(seal.red_mark_pages(pdf_with(3), 2), [])

    def test_rectangular_red_stamp_and_small_emblem_are_not_seals(self):
        def marks(_index, page):
            page.draw_rect(pymupdf.Rect(60, 400, 60 + 40 * MM, 400 + 36 * MM), color=RED, fill=RED)  # "HỎA TỐC"-like box
            ring(page, diameter_mm=10, centre=(450, 120))                                         # e-signature emblem
            ring(page, diameter_mm=80, centre=(300, 600))                                         # too large
        result = seal.find_seal(pdf_with(1, marks), ".pdf")
        self.assertEqual((result["reason"], result["colour"]), ("not_found", None))
        self.assertNotIn("page", result)

    def test_a_printed_emblem_is_not_a_seal_and_the_search_goes_on_to_the_seal(self):
        # Round 6: two appendix covers printing the national emblem came after the signature page; the seal is earlier.
        payload = pdf_with(4, lambda i, page: emblem(page) if i in (2, 3) else ring(page) if i == 0 else None)
        result = seal.find_seal(payload, ".pdf")
        self.assertEqual((result["reason"], result["colour"], result["page"]), ("found", "red", 1))
        self.assertEqual(result["pages_checked"], [4, 3, 2, 1])
        self.assertTrue(36 <= result["size_mm"][0] <= 44)  # the evidence is the seal's box, not the emblem's
        self.assertEqual(sorted({mark["page"] for mark in result["rejected_marks"]}), [3, 4])
        for mark in result["rejected_marks"]:
            self.assertEqual(mark["reason"], "two_colour_print")
            self.assertGreaterEqual(mark["yellow_per_red"], seal.YELLOW_PER_RED)
        self.assertEqual([mark["page"] for mark in seal.red_mark_pages(payload, 2)], [1])

    def test_an_emblem_alone_is_no_seal_and_a_signature_across_a_seal_keeps_it_one(self):
        result = seal.find_seal(pdf_with(1, lambda _i, page: emblem(page)), ".pdf")
        self.assertEqual((result["reason"], result["colour"]), ("not_found", None))
        self.assertNotIn("page", result)
        self.assertTrue(result["rejected_marks"])

        def signed(_index, page):
            ring(page)
            page.draw_line((330, 620), (470, 680), color=(.1, .1, .8), width=2)  # a blue signature over the seal
        result = seal.find_seal(pdf_with(1, signed), ".pdf")
        self.assertEqual((result["reason"], result["page"]), ("found", 1))
        self.assertNotIn("rejected_marks", result)

    def test_a_seal_on_yellowed_or_tinted_paper_is_still_a_seal_and_an_emblem_on_it_is_not(self):
        # review, 2026-11-10: the paper's own yellow is not a second ink
        for name, paper in {"aged paper": (235 / 255, 220 / 255, 175 / 255), "yellow paper": (1, 240 / 255, 120 / 255)}.items():
            def on_paper(_index, page, paper=paper):
                page.draw_rect(page.rect, color=None, fill=paper)
                ring(page)
            result = seal.find_seal(pdf_with(1, on_paper), ".pdf")
            self.assertEqual((result["reason"], result["page"]), ("found", 1), name)
            self.assertNotIn("rejected_marks", result, name)

        def emblem_on_aged_paper(_index, page):
            page.draw_rect(page.rect, color=None, fill=(235 / 255, 220 / 255, 175 / 255))
            emblem(page)
        result = seal.find_seal(pdf_with(1, emblem_on_aged_paper), ".pdf")
        self.assertEqual(result["reason"], "not_found")
        self.assertEqual({mark["reason"] for mark in result["rejected_marks"]}, {"two_colour_print"})

    def test_pages_named_first_are_checked_before_the_others(self):
        # Round 6: a consolidated text's seal is on its authentication block's page, before appendices with an emblem.
        payload = pdf_with(5, lambda i, page: ring(page) if i == 1 else emblem(page) if i == 4 else None)
        hinted = seal.find_seal(payload, ".pdf", first_pages=(2,))
        self.assertEqual((hinted["page"], hinted["pages_checked"]), (2, [2]))
        self.assertNotIn("rejected_marks", hinted)
        plain = seal.find_seal(payload, ".pdf")
        self.assertEqual((plain["page"], plain["pages_checked"]), (2, [5, 4, 3, 2]))
        for nonsense in ((0,), (9,), (True,), ("2",), (2.0,)):
            self.assertEqual(seal.page_order(5, nonsense), [4, 3, 2, 1, 0], nonsense)
        self.assertEqual(seal.page_order(5, (2, 2)), [1, 4, 3, 2, 0])

    def test_with_colour_but_no_seal_at_the_ends_the_middle_pages_are_checked_too(self):
        def draw(index, page):
            if index == 25:
                ring(page)
            if index == 49:  # a coloured signing stamp on the last page: the document shows colour
                page.draw_rect(pymupdf.Rect(60, 100, 160, 120), color=BLUE, fill=BLUE)
        result = seal.find_seal(pdf_with(50, draw), ".pdf")
        self.assertEqual((result["reason"], result["page"]), ("found", 26))
        tail, head = list(range(50, 30, -1)), list(range(1, 21))
        self.assertEqual(result["pages_checked"], tail + head + [30, 29, 28, 27, 26])
        middle = seal.middle_order(100)
        self.assertEqual((len(middle), middle[0], middle[-1]), (seal.MIDDLE_PAGES, 79, 20))
        self.assertEqual(seal.middle_order(40), [])

    def test_a_black_and_white_scan_or_a_black_text_document_is_not_searched_further(self):
        result = seal.find_seal(pdf_with(45, grey_scan_pages=set(range(45))), ".pdf")
        self.assertEqual((result["reason"], len(result["pages_checked"])), ("black_and_white", seal.TAIL_PAGES + seal.HEAD_PAGES))
        # black text only at both ends (no colour seen): the middle is not rendered, as before round 6
        result = seal.find_seal(pdf_with(50, lambda i, page: ring(page) if i == 25 else None), ".pdf")
        self.assertEqual((result["reason"], len(result["pages_checked"])), ("not_found", seal.TAIL_PAGES + seal.HEAD_PAGES))
        self.assertEqual(seal.red_mark_pages(pdf_with(50, lambda i, page: ring(page) if i == 25 else None), 2), [])

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

    def test_the_seal_check_starts_on_the_authentication_block_page(self):
        reply = {"method": seal.METHOD, "reason": "not_found", "colour": None}
        fast_result = {"method": "metadata_fast", "consolidation_block": {"page": 3}}
        with patch.object(api, "extract_metadata_fast", return_value=fast_result), \
             patch.object(api, "find_seal", return_value=reply) as check:
            status, _, body = request("/api/ocr", {"mode": "metadata_fast"}, "native.pdf", pdf_bytes(header()))
        self.assertEqual(status, 200, body)
        self.assertEqual(check.call_args.args[1:], (".pdf", (3,)))
        for result in ({}, {"consolidation_block": None}, {"consolidation_block": {"page": True}},
                       {"consolidation_block": {"page": 0}}, {"consolidation_block": {"page": "3"}}):
            self.assertEqual(api.seal_pages_first(result), (), result)

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

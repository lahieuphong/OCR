"""Synthetic PDF tests: source selection must never damage original OCR evidence."""
from __future__ import annotations

import copy
import string
import unittest
from unittest.mock import patch

import fitz

from demo.local_pdf_ocr.backend.engine import iter_images
from demo.local_pdf_ocr.backend.hybrid_h1 import apply_hybrid_h1

VOCABULARY = set(string.ascii_letters + string.digits + " .,:;/-()@+%\"'")


def fixture(text="Notice 123/ABC", *, text_options=None, rotated=False, cropped=False, blank=False, covered=False):
    with fitz.open() as doc:
        page = doc.new_page(width=300, height=200)
        if not blank:
            page.insert_text((20, 40), text, fontsize=12, **(text_options or {}))
            words = page.get_text("words")
            rect = (min(w[0] for w in words), min(w[1] for w in words),
                    max(w[2] for w in words), max(w[3] for w in words))
        else:
            rect = (20, 25, 140, 45)
            page.draw_rect(fitz.Rect(rect), color=(0, 0, 0), fill=(0, 0, 0))
        if covered:
            page.draw_rect(fitz.Rect(rect), color=(0, 0, 0), fill=(0, 0, 0))
        if rotated:
            page.set_rotation(90)
        if cropped:
            page.set_cropbox(fitz.Rect(0, 0, 250, 180))
        content = doc.tobytes()
    image = next(iter_images(content, ".pdf"))[1]
    x0, y0, x1, y1 = [v * 2 for v in rect]
    polygon = [[x0 - 2, y0 - 2], [x1 + 2, y0 - 2], [x1 + 2, y1 + 2], [x0 - 2, y1 + 2]]
    line = {"line_index": 1, "polygon": polygon, "text": "Notice 128/ABC", "hit_decoder_limit": False}
    page = {"page": 1, "width": image.width, "height": image.height,
            "lines": [line], "text": line["text"], "reading_order": "original_order"}
    result = {"method": "vietocr_ocr", "used_ocr": True, "engine": "synthetic OCR",
              "pages": [page], "text": page["text"], "page_count": 1, "line_count": 1,
              "decoder_limit_hits": 0, "elapsed_ms": 25, "limitations": ["original limitation"]}
    return content, result


class HybridSourceSelectionTests(unittest.TestCase):
    def test_trusted_visible_text_and_original_evidence_remain_separate(self):
        content, baseline = fixture()
        original = copy.deepcopy(baseline)
        with patch("demo.local_pdf_ocr.backend.engine.OnnxVietocrB", side_effect=AssertionError("No inference")), \
             patch("demo.local_pdf_ocr.backend.engine.PaddleTextDetector", side_effect=AssertionError("No detector")):
            result = apply_hybrid_h1(content, "synthetic.pdf", baseline, vocabulary=VOCABULARY)
        self.assertEqual(baseline, original)
        self.assertEqual(result["method"], "hybrid_h1")
        self.assertTrue(result["experimental"])
        self.assertFalse(result["deployment_approved"])
        self.assertEqual(result["h1"]["gates_sha256"], "227a2a272661b86077c47b230d7977e63e802fe276ecdc86336275ce2c5e672f")
        self.assertEqual(result["text"], "Notice 123/ABC")
        line = result["pages"][0]["lines"][0]
        self.assertEqual(line["ocr_text"], "Notice 128/ABC")
        self.assertEqual(line["text_source"], "pdf_text")
        self.assertIsNone(line["fallback_reason"])
        self.assertEqual((result["h1"]["native_lines"], result["h1"]["ocr_lines"]), (1, 0))
        self.assertEqual(line["polygon"], baseline["pages"][0]["lines"][0]["polygon"])
        self.assertEqual(result["pages"][0]["reading_order"], "original_order")
        self.assertEqual(result["decoder_limit_hits"], baseline["decoder_limit_hits"])

    def test_scan_keeps_ocr_bytes_including_combining_characters(self):
        content, baseline = fixture(blank=True)
        raw = "Do\u0302ng  128/ABC\r"
        baseline["pages"][0]["lines"][0]["text"] = raw
        baseline["pages"][0]["text"] = raw
        baseline["text"] = raw
        result = apply_hybrid_h1(content, "scan.pdf", baseline)
        line = result["pages"][0]["lines"][0]
        self.assertEqual(line["text"].encode("utf-8"), raw.encode("utf-8"))
        self.assertEqual(line["ocr_text"], raw)
        self.assertEqual(line["text_source"], "ocr")
        self.assertEqual(line["fallback_reason"], "page_no_text_layer")

    def test_invisible_white_or_covered_text_never_earns_trust(self):
        for options in ({"text_options": {"render_mode": 3}}, {"text_options": {"fill_opacity": 0}},
                        {"text_options": {"color": (1, 1, 1)}}, {"covered": True}):
            with self.subTest(options=options):
                content, baseline = fixture(**options)
                result = apply_hybrid_h1(content, "synthetic.pdf", baseline, vocabulary=VOCABULARY)
                line = result["pages"][0]["lines"][0]
                self.assertEqual(result["text"], baseline["text"])
                self.assertEqual(line["text_source"], "ocr")
                self.assertTrue(line["fallback_reason"])

    def test_rotation_and_cropbox_fall_back_without_reordering(self):
        for options in ({"rotated": True}, {"cropped": True}):
            with self.subTest(options=options):
                content, baseline = fixture(**options)
                result = apply_hybrid_h1(content, "geometry.pdf", baseline)
                line = result["pages"][0]["lines"][0]
                self.assertEqual(line["fallback_reason"], "page_unsupported_geometry")
                self.assertEqual(result["text"], baseline["text"])
                self.assertEqual(line["polygon"], baseline["pages"][0]["lines"][0]["polygon"])

    def test_untrusted_font_and_vocabulary_fall_back(self):
        content, baseline = fixture()
        with patch("demo.local_pdf_ocr.backend.hybrid_h1.font_trust", return_value={}):
            result = apply_hybrid_h1(content, "synthetic.pdf", baseline)
        self.assertEqual(result["pages"][0]["lines"][0]["fallback_reason"], "untrusted_font_mapping")
        result = apply_hybrid_h1(content, "synthetic.pdf", baseline, vocabulary=set("Notice 128/ABC"))
        self.assertIn("out_of_vocabulary_character", result["pages"][0]["lines"][0]["failed_gates"])
        self.assertEqual(result["text"], baseline["text"])

    def test_token_count_or_large_text_disagreement_keeps_raw_ocr(self):
        for text, reason in (("Notice128/ABC", "token_count_differs_from_b1024"),
                             ("xxxxx yyyy", "gross_mismatch_with_b1024")):
            with self.subTest(text=text):
                content, baseline = fixture()
                baseline["text"] = baseline["pages"][0]["text"] = text
                baseline["pages"][0]["lines"][0]["text"] = text
                result = apply_hybrid_h1(content, "synthetic.pdf", baseline)
                self.assertEqual(result["text"], text)
                self.assertEqual(result["pages"][0]["lines"][0]["fallback_reason"], reason)

    def test_missing_pdf_visibility_evidence_fails_closed(self):
        content, baseline = fixture()
        with patch("demo.local_pdf_ocr.backend.hybrid_h1.page_words", side_effect=KeyError("char_flags")):
            result = apply_hybrid_h1(content, "synthetic.pdf", baseline)
        self.assertEqual(result["text"], baseline["text"])
        self.assertEqual(result["pages"][0]["lines"][0]["fallback_reason"], "page_text_unavailable")

    def test_resource_budget_keeps_original_text(self):
        content, baseline = fixture()
        with patch("demo.local_pdf_ocr.backend.hybrid_h1.MAX_H1_WORDS", 0):
            result = apply_hybrid_h1(content, "synthetic.pdf", baseline)
        self.assertEqual(result["text"], baseline["text"])
        self.assertEqual(result["pages"][0]["lines"][0]["fallback_reason"], "page_text_limit")


class HybridInputValidationTests(unittest.TestCase):
    def test_non_pdf_and_corrupt_pdf_are_rejected(self):
        for filename, content in (("image.png", b"\x89PNG\r\n\x1a\ninvalid"), ("bad.pdf", b"%PDF-invalid")):
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                apply_hybrid_h1(content, filename, {})

    def test_inconsistent_page_text_and_geometry_are_rejected(self):
        mutations = [
            lambda result: result.update(method="native_text"),
            lambda result: result.update(text="unrelated"),
            lambda result: result["pages"][0].update(page=2),
            lambda result: result["pages"][0].update(text="unrelated"),
            lambda result: result["pages"][0].update(width=601),
            lambda result: result["pages"][0]["lines"][0]["polygon"][0].__setitem__(0, float("nan")),
            lambda result: result["pages"][0]["lines"][0]["polygon"][0].__setitem__(0, -1),
            lambda result: result["pages"][0]["lines"][0].update(polygon=[[2, 2]] * 4),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                content, baseline = fixture()
                mutation(baseline)
                with self.assertRaises(ValueError):
                    apply_hybrid_h1(content, "synthetic.pdf", baseline)

    def test_password_and_page_limit_are_rejected(self):
        content, baseline = fixture()
        with fitz.open(stream=content, filetype="pdf") as doc:
            encrypted = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user")
        with self.assertRaises(ValueError):
            apply_hybrid_h1(encrypted, "protected.pdf", baseline)
        with fitz.open() as doc:
            for _ in range(7):
                doc.new_page()
            too_many = doc.tobytes()
        with self.assertRaises(ValueError):
            apply_hybrid_h1(too_many, "large.pdf", baseline)


if __name__ == "__main__":
    unittest.main()

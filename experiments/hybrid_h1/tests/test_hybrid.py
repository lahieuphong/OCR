"""H1 on synthetic PDFs built in memory: every gate that must fall back does; fallback text is A0's bytes."""
import hashlib
import json
import string
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pymupdf as fitz

from experiments.hybrid_h1.gates import font_trust
from experiments.hybrid_h1.hybrid import apply_decisions, decide_page, document_fonts, refuse_reserved, run

ZOOM = 2.0
VOCABULARY = set(string.ascii_letters + string.digits + " .,:;/-()@+%\"'")


def render(page):
    pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), colorspace=fitz.csRGB, alpha=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)


def polygon(rect, pad_px=2):
    x0, y0, x1, y1 = (v * ZOOM for v in rect)
    return [[x0 - pad_px, y0 - pad_px], [x1 + pad_px, y0 - pad_px], [x1 + pad_px, y1 + pad_px], [x0 - pad_px, y1 + pad_px]]


def words_rect(page, y_from, y_to):
    boxes = [w[:4] for w in page.get_text("words") if y_from <= (w[1] + w[3]) / 2 <= y_to]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def a0_page(lines):
    return {"page": 1, "width": 600, "height": 400, "text": "\n".join(t for t, _ in lines),
            "lines": [{"line_index": i, "polygon": p, "text": t, "hit_decoder_limit": False} for i, (t, p) in enumerate(lines, 1)]}


def decide(doc, page, lines):
    return decide_page(page, render(page), a0_page(lines), ZOOM, font_trust(document_fonts(doc)), VOCABULARY)


def new_page():
    doc = fitz.open()
    return doc, doc.new_page(width=300, height=200)


def by_line(decisions):
    return {d["line_index"]: d for d in decisions}


class Selection(unittest.TestCase):
    def test_visible_text_is_selected_and_every_fallback_keeps_a0_bytes(self):
        doc, page = new_page()
        page.insert_text((20, 30), "Email: thongtin@example.vn", fontsize=11)
        page.insert_text((20, 60), "Hello world", fontsize=11)
        page.insert_text((20, 90), "Ha Noi, ngay 08 thang 10", fontsize=11)
        lines = [("Email: thongtin@example.yn", polygon(words_rect(page, 20, 35))),
                 ("Hello world", polygon(words_rect(page, 50, 65))),
                 ("Ha Noi, ngay 08 thang10", polygon(words_rect(page, 80, 95)))]
        record, decisions = decide(doc, page, lines)
        d = by_line(decisions)
        self.assertEqual(record["class"], "partial_text")  # fewer than 200 visible characters
        self.assertEqual((d[1]["source"], d[1]["text"]), ("pdf_text", "Email: thongtin@example.vn"))
        self.assertEqual((d[2]["source"], d[2]["text"]), ("pdf_text", "Hello world"))
        self.assertEqual((d[3]["fallback_reason"], d[3]["text"]), ("token_count_differs_from_b1024", "Ha Noi, ngay 08 thang10"))
        export = {"pages": [a0_page(lines)], "text": a0_page(lines)["text"]}
        meta = {"document_hash": "x", "model_version": {"b1024": "b", "pdf_text": "p"}}
        h1 = apply_decisions(export, {1: (record, decisions)}, meta)
        out = h1["pages"][0]["lines"]
        self.assertEqual(out[2]["text"].encode(), lines[2][0].encode())
        self.assertEqual(out[2]["source"], "b1024")
        self.assertEqual((out[0]["source"], out[0]["b1024_text"]), ("pdf_text", lines[0][0]))
        self.assertEqual(h1["pages"][0]["text"], "\n".join(line["text"] for line in out))
        self.assertEqual(h1["text"], h1["pages"][0]["text"])
        self.assertLessEqual({"source", "fallback_reason", "page", "bbox", "model_version", "document_hash"}, set(out[0]))
        self.assertEqual(export["pages"][0]["lines"][0]["text"], lines[0][0])  # the A0 input is untouched


class Fallback(unittest.TestCase):
    def test_text_a_reader_cannot_see(self):
        for kwargs, reason in (({"render_mode": 3}, "invisible_text"), ({"fill_opacity": 0}, "invisible_text"),
                               ({"color": (1, 1, 1)}, "word_without_ink")):
            with self.subTest(kwargs):
                doc, page = new_page()
                for y in (30, 50, 70):
                    page.insert_text((20, y), "Visible line of ordinary text here", fontsize=11)
                page.insert_text((20, 120), "Hidden", fontsize=11, **kwargs)
                record, decisions = decide(doc, page, [("Hiddem", polygon(words_rect(page, 110, 125)))])
                self.assertEqual(record["class"], "partial_text")
                self.assertEqual((decisions[0]["fallback_reason"], decisions[0]["text"]), (reason, "Hiddem"))

    def test_text_under_a_later_image_is_covered(self):
        doc, page = new_page()
        page.insert_text((20, 30), "Signer Name", fontsize=11)
        rect = words_rect(page, 20, 35)
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), False)
        pix.set_rect(pix.irect, (90, 90, 90))
        page.insert_image(fitz.Rect(rect[0] - 2, rect[1] - 2, rect[2] + 2, rect[3] + 2), pixmap=pix)
        record, decisions = decide(doc, page, [("Slgner Name", polygon(rect))])
        self.assertEqual(record["class"], "hidden_text_layer")
        self.assertEqual(decisions[0]["fallback_reason"], "page_hidden_text_layer")
        self.assertIn("covered_text", decisions[0]["failed_gates"])

    def test_ink_without_a_text_layer_word(self):
        doc, page = new_page()
        page.draw_rect(fitz.Rect(110, 22, 125, 32), color=(0, 0, 0), fill=(0, 0, 0))  # e.g. a stamp or handwriting
        page.insert_text((20, 30), "Printed", fontsize=11)
        rect = words_rect(page, 20, 35)
        _, decisions = decide(doc, page, [("Printed X", polygon((rect[0], rect[1], 126, rect[3])))])
        self.assertEqual(decisions[0]["fallback_reason"], "unexplained_ink")
        self.assertGreater(decisions[0]["checks"]["unexplained_ink_share"], 0.1)

    def test_page_without_text_layer_keeps_every_line(self):
        doc, page = new_page()
        page.draw_rect(fitz.Rect(20, 20, 120, 32), color=(0, 0, 0), fill=(0, 0, 0))
        record, decisions = decide(doc, page, [("Scanned words", polygon((20, 20, 120, 32)))])
        self.assertEqual(record["class"], "no_text_layer")
        self.assertEqual((decisions[0]["fallback_reason"], decisions[0]["text"]), ("page_no_text_layer", "Scanned words"))

    def test_geometry_gates(self):
        doc, page = new_page()
        page.insert_text((20, 30), "Twice", fontsize=11)
        page.insert_text((20, 30), "Twice", fontsize=11)
        page.insert_text((20, 60), "Upper line", fontsize=11)
        page.insert_text((20, 74), "Lower line", fontsize=11)
        page.insert_text((20, 120), "Shared words", fontsize=11)
        shared = words_rect(page, 110, 125)
        lines = [("Twice", polygon(words_rect(page, 20, 35))),
                 ("Upper line Lower line", polygon(words_rect(page, 50, 80))),
                 ("Shared words", polygon(shared)),
                 ("Shared", polygon((shared[0], shared[1], shared[2] - 10, shared[3])))]
        _, decisions = decide(doc, page, lines)
        d = by_line(decisions)
        self.assertEqual(d[1]["fallback_reason"], "duplicate_text")
        self.assertEqual(d[2]["fallback_reason"], "multi_line_text")
        self.assertIn("word_shared_between_polygons", d[3]["failed_gates"])
        self.assertEqual(d[3]["source"], "b1024")

    def test_superscript_footnote_marker(self):
        doc, page = new_page()
        page.insert_text((20, 40), "Phu luc I", fontsize=12)
        end = page.get_text("words")[-1][2]
        page.insert_text((end + 0.3, 35), "11", fontsize=7)
        _, decisions = decide(doc, page, [("Phu luc III", polygon(words_rect(page, 25, 45)))])
        self.assertEqual(decisions[0]["fallback_reason"], "superscript_text")

    def test_gross_mismatch_with_b1024(self):
        doc, page = new_page()
        page.insert_text((20, 30), "alpha beta", fontsize=11)
        _, decisions = decide(doc, page, [("xxxxx yyyy", polygon(words_rect(page, 20, 35)))])
        self.assertEqual(decisions[0]["fallback_reason"], "gross_mismatch_with_b1024")


class Run(unittest.TestCase):
    def test_reserved_blind_document_is_refused(self):
        with self.assertRaisesRegex(ValueError, "reserved"):
            refuse_reserved("any/folder/30.signed.pdf")

    def test_end_to_end_on_a_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            doc, page = new_page()
            page.insert_text((20, 30), "Email: thongtin@example.vn", fontsize=11)
            rect = words_rect(page, 20, 35)
            pdf = tmp / "synthetic.pdf"
            doc.save(pdf)
            export = {"model": "phase4_exp_b_width1024", "elapsed_ms": 5, "text": "Email: thongtin@example.yn",
                      "pages": [{**a0_page([("Email: thongtin@example.yn", polygon(rect))]), "elapsed_ms": 5}]}
            ocr_json = tmp / "synthetic_vietocr_ocr_header_split.json"
            ocr_json.write_text(json.dumps(export), encoding="utf-8")
            source = {"set": "test", "document": "synthetic.pdf", "pdf": str(pdf), "ocr_json": str(ocr_json),
                      "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                      "ocr_json_sha256": hashlib.sha256(ocr_json.read_bytes()).hexdigest()}
            manifest = run([source], tmp / "out")
            self.assertEqual(manifest["recognizer_inference_run"], 0)
            self.assertFalse(manifest["reference_text_used"])
            h1 = json.loads((tmp / "out/documents/synthetic.h1.json").read_text(encoding="utf-8"))
            self.assertEqual(h1["text"], "Email: thongtin@example.vn")
            self.assertEqual(h1["pages"][0]["lines"][0]["document_hash"], source["pdf_sha256"])
            with self.assertRaisesRegex(ValueError, "will not overwrite"):
                run([source], tmp / "out")
            with self.assertRaisesRegex(ValueError, "source changed"):
                run([{**source, "pdf_sha256": "0" * 64}], tmp / "out2")


if __name__ == "__main__":
    unittest.main()

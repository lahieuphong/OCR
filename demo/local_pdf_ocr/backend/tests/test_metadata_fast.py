"""Synthetic model-free fast-mode contracts, not recognition/performance scores."""
import hashlib
import io
import json
import os
import re
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pymupdf as fitz
from PIL import Image

from demo.local_pdf_ocr.backend import metadata_fast as fast
from demo.local_pdf_ocr.backend.contract import DemoConfigurationError


def header(title="NGHỊ ĐỊNH", long=False, boundary="Căn cứ Luật tổ chức Chính phủ;"):
    rows = [("CHÍNH PHỦ", 40, 40), ("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", 300, 40),
            ("Số: 00103/2026/QĐ-QA", 40, 90), ("Hà Nội, ngày 07 tháng 04 năm 2026", 300, 90),
            (title, 230, 130), ("Sửa đổi, bổ sung một số điều của văn bản", 100, 165)]
    if long:
        rows += [(f"Trích yếu tiếp nối dòng {i}", 100, 190 + i * 35) for i in range(8)]
        rows += [(boundary, 40, 500), ("Điều 1. Không được nhận dạng phần thân.", 40, 530)]
    else:
        rows += [("Giữ nguyên dấu tiếng Việt và số tham chiếu.", 100, 190),
                 (boundary, 40, 230), ("Điều 1. Không được nhận dạng phần thân.", 40, 280)]
    return rows


def pdf_bytes(rows=(), pages=6):
    pdf = fitz.open()
    page = pdf.new_page(width=600, height=800)
    if rows:
        # Use PyMuPDF's bundled Helvetica and Unicode fallback fonts. Host
        # font cmap aliases can extract authored ASCII spaces as NBSP instead.
        writer = fitz.TextWriter(page.rect)
        for text, x, y in rows:
            writer.append((x, y), text, fontsize=9)
        writer.write_text(page)
    for _ in range(pages - 1):
        pdf.new_page(width=600, height=800)
    result = pdf.tobytes()
    pdf.close()
    return result


def image_bytes(kind="PNG", size=(600, 800), exif=None):
    target = io.BytesIO()
    options = {"exif": exif} if exif is not None else {}
    Image.new("RGB", size, "white").save(target, kind, **options)
    return target.getvalue()


class FakeDetector:
    def __init__(self, rows, dimensions_change=False):
        self.rows = rows
        self.dimensions_change = dimensions_change
        self.regions = {}
        self.crop_calls = []

    def detect_regions(self, image):
        polygons = []
        for index, (text, x, y) in enumerate(self.rows):
            if y + 12 <= image.height:
                quad = [[x, y], [x + 55, y], [x + 55, y + 12], [x, y + 12]]
                self.regions[tuple(map(tuple, quad))] = (index, text)
                polygons.append(quad)
        return image, sorted(polygons, key=lambda q: (q[0][1], q[0][0]))

    def crop_region(self, image, quad):
        index, text = self.regions[tuple(map(tuple, quad))]
        size = (16, 10) if self.dimensions_change and image.height > 360 else (20, 8)
        crop = Image.new("RGB", size, (index + 1, 0, 0))
        crop.info["qa_text"] = text
        self.crop_calls.append(text)
        return crop


class FakeEngine:
    def __init__(self, rows=None, dimensions_change=False):
        self.initialization_started_at = time.perf_counter()
        self.initialization_ms = .125
        self.detector = FakeDetector(rows if rows is not None else header(), dimensions_change)
        self.predictions = []
        self.recognizer = SimpleNamespace(predict=self.predict)

    def predict(self, crop):
        self.predictions.append(crop.info["qa_text"])
        return crop.info["qa_text"], False


class FastMetadataTests(unittest.TestCase):
    def run_fast(self, payload, name, provider):
        with patch.object(fast, "offline_engine", side_effect=lambda callback: callback()):
            return fast.extract_metadata_fast(payload, name, provider)

    def test_native_pdf_fixture_roundtrips_exact_unicode_without_host_fonts(self):
        rows = header()
        rows[5] = ("Triển khai ký số và quản lý chữ ký số.", 100, 165)
        with patch.object(Path, "is_file", side_effect=AssertionError("Fixture must not select a host font")):
            payload = pdf_bytes(rows)
        # Prove the authored PDF contains the literal strings before testing
        # production extraction: do not normalize font-generated substitutions.
        with fitz.open(stream=payload, filetype="pdf") as pdf:
            lines = ["".join(span["text"] for span in line["spans"])
                     for block in pdf[0].get_text("dict")["blocks"] if block["type"] == 0
                     for line in block["lines"]]
        self.assertEqual(lines, [text for text, _x, _y in rows])

    def test_six_page_source_never_accesses_or_renders_page_two(self):
        renders = []
        class FirstPage:
            rect = SimpleNamespace(width=600, height=800)
            def get_text(self, *_args, **_kwargs):
                return {"blocks": []}
            def get_pixmap(self, **kwargs):
                clip = kwargs["clip"]
                renders.append(list(clip))
                image = Image.new("RGB", (1200, round(clip.height * 2)), "white")
                return SimpleNamespace(width=image.width, height=image.height, samples=image.tobytes())
        class SixPages:
            needs_pass = False
            def __len__(self): return 6
            def __getitem__(self, index):
                if index != 0: raise AssertionError("Fast must not inspect/render an appendix page")
                return FirstPage()
            def close(self): pass
        engine = FakeEngine([(text, x * 2, y * 2) for text, x, y in header()])
        with patch.object(fitz, "open", return_value=SixPages()):
            result = self.run_fast(b"%PDF-1.7\n", "six.pdf", lambda: engine)
        self.assertEqual(result["source_page_count"], 6)
        self.assertEqual(result["page_count"], 1)
        self.assertEqual(result["processed_pages"], [1])
        self.assertEqual(result["inspected_pages"], [1])
        self.assertTrue(result["partial_result"])
        self.assertEqual(result["pages"][0]["height"], 1600)
        self.assertEqual(len(renders), 1)
        self.assertLessEqual(renders[0][3], 800 * .45)
        self.assertFalse(any(text.startswith("Điều 1") for text in engine.predictions))

    def test_long_source_pdf_reads_only_page_one_while_full_modes_keep_six_pages(self):
        from demo.local_pdf_ocr.backend.text_layer import extract_pdf_text
        payload = pdf_bytes(header("CÔNG VĂN", boundary="Kính gửi: Cơ quan QA"), pages=40)
        with patch.object(fast, "offline_engine", side_effect=AssertionError("native header must not initialize OCR")):
            result = fast.extract_metadata_fast(payload, "long.pdf", Mock())
        self.assertEqual(result["source_page_count"], 40)
        self.assertEqual((result["page_count"], result["inspected_pages"], result["processed_pages"]), (1, [1], []))
        self.assertTrue(result["partial_result"])
        with self.assertRaises(ValueError):
            extract_pdf_text(payload, "long.pdf")

    def test_genuine_native_headers_need_no_model_or_render(self):
        for title in ("NGHỊ ĐỊNH", "CÔNG VĂN", "QUYẾT ĐỊNH", "NGHỊ QUYẾT"):
            with self.subTest(title=title), patch.object(fast, "offline_engine", side_effect=AssertionError("native must not initialize OCR")):
                result = fast.extract_metadata_fast(pdf_bytes(header(title, boundary="Kính gửi: Cơ quan QA")), "native.pdf", Mock())
            self.assertFalse(result["used_ocr"])
            self.assertEqual(result["processed_pages"], [])
            self.assertEqual(result["source_page_count"], 6)
            self.assertEqual(result["pages"][0]["coordinate_system"], "pdf_points")
            self.assertTrue(result["fast_metadata"]["header_complete"])
            self.assertEqual(result["timings_ms"]["model_init"], 0)
            self.assertEqual(result["timings_ms"]["render"], 0)

    def test_e_signature_text_is_not_a_native_header_or_issue_date(self):
        rows = [("Digitally signed by Portal", 180, 15), ("Signing time: 09/04/2026", 180, 30)]
        provider = Mock(side_effect=DemoConfigurationError("models missing"))
        with patch.object(fast, "offline_engine", side_effect=lambda callback: callback()):
            with self.assertRaisesRegex(DemoConfigurationError, "models missing"):
                fast.extract_metadata_fast(pdf_bytes(rows), "signature.pdf", provider)
        provider.assert_called_once()

    def test_roi_grows_only_on_first_page_and_reuses_exact_crops(self):
        engine = FakeEngine(header(long=True))
        result = self.run_fast(image_bytes(), "long.png", lambda: engine)
        attempts = result["fast_metadata"]["roi_attempts"]
        self.assertEqual(len(attempts), 2)
        self.assertGreater(attempts[1]["reused_lines"], 0)
        self.assertEqual(engine.predictions.count("CHÍNH PHỦ"), 1)
        self.assertLessEqual(result["pages"][0]["roi"][3], 800 * .8)
        self.assertFalse(any(text.startswith("Điều 1") for text in engine.predictions))

    def test_same_pixel_bytes_with_different_crop_dimensions_are_not_reused(self):
        engine = FakeEngine(header(long=True), dimensions_change=True)
        result = self.run_fast(image_bytes(), "dimensions.png", lambda: engine)
        self.assertEqual(result["fast_metadata"]["roi_attempts"][1]["reused_lines"], 0)
        self.assertEqual(engine.predictions.count("CHÍNH PHỦ"), 2)

    def test_missing_header_is_partial_review_without_full_page_fallback(self):
        engine = FakeEngine([("Một trang bìa chưa có header", 40, 50)])
        result = self.run_fast(image_bytes(), "cover.png", lambda: engine)
        self.assertEqual(result["processed_pages"], [1])
        self.assertEqual(len(result["fast_metadata"]["roi_attempts"]), 3)
        self.assertTrue(result["fast_metadata"]["roi_limit_reached"])
        self.assertTrue(result["fast_metadata"]["needs_review"])

    def test_body_seen_with_handwritten_number_or_date_does_not_grow_the_region(self):
        rows = header()
        rows[2] = ("Số:", 40, 90)                       # number left blank or handwritten and unreadable
        rows[3] = ("Hà Nội, ngày tháng 04 năm 2026", 300, 90)
        engine = FakeEngine(rows)
        result = self.run_fast(image_bytes(), "handwritten.png", lambda: engine)
        meta = result["fast_metadata"]
        self.assertEqual(len(meta["roi_attempts"]), 1)
        self.assertEqual(meta["stopped"], "body_boundary_seen")
        self.assertFalse(meta["roi_limit_reached"])
        self.assertIn("roi_growth_stopped:body_boundary_seen", meta["reasons"])
        self.assertIn("missing_header_evidence:document_number,issued_date", meta["reasons"])
        self.assertEqual(engine.predictions.count("CHÍNH PHỦ"), 1)

    def test_notice_without_body_marker_stops_after_the_subject_allowance(self):
        rows = [("VĂN PHÒNG CHÍNH PHỦ", 40, 40), ("Số: 180/TB-VPCP", 40, 70), ("Hà Nội, ngày 07 tháng 4 năm 2026", 300, 70),
                ("THÔNG BÁO", 230, 100), ("Kết luận của Thường trực Chính phủ", 100, 120)]
        rows += [(f"Nội dung thông báo dòng {i}", 40, 140 + i * 15) for i in range(30)]
        engine = FakeEngine(rows)
        result = self.run_fast(image_bytes(), "notice.png", lambda: engine)
        meta = result["fast_metadata"]
        self.assertEqual((len(meta["roi_attempts"]), meta["stopped"]), (1, "subject_line_allowance"))
        title_at = [line["text"] for line in result["pages"][0]["lines"]].index("THÔNG BÁO") + 1
        self.assertEqual(result["line_count"], title_at + fast.SUBJECT_LINE_ALLOWANCE)
        self.assertNotIn("Nội dung thông báo dòng 20", engine.predictions)

    def test_telegram_title_anchors_the_subject_allowance_like_any_title(self):
        # Owner, 2026-11-10: "CÔNG ĐIỆN" is a document title. A telegram has no "Căn cứ"/"Kính gửi" either.
        rows = [("THỦ TƯỚNG CHÍNH PHỦ", 40, 40), ("Số: 15/CĐ-KT", 40, 70), ("Hà Nội, ngày 07 tháng 4 năm 2026", 300, 70),
                ("CÔNG ĐIỆN", 230, 100), ("Về việc kiểm thử công điện tổng hợp", 100, 120), ("THỦ TƯỚNG CHÍNH PHỦ điện:", 120, 140)]
        rows += [(f"Nội dung công điện dòng {i}", 40, 160 + i * 15) for i in range(30)]
        engine = FakeEngine(rows)
        result = self.run_fast(image_bytes(), "telegram.png", lambda: engine)
        meta = result["fast_metadata"]
        self.assertEqual((len(meta["roi_attempts"]), meta["stopped"]), (1, "subject_line_allowance"))
        self.assertTrue(meta["roi_attempts"][0]["evidence"]["document_heading"])
        title_at = [line["text"] for line in result["pages"][0]["lines"]].index("CÔNG ĐIỆN") + 1
        self.assertEqual(result["line_count"], title_at + fast.SUBJECT_LINE_ALLOWANCE)

    def test_date_line_missing_a_space_at_a_letter_digit_boundary_is_date_evidence(self):
        rows = header()
        rows[3] = ("Hà Nội, ngày 07 tháng 04năm 2026", 300, 90)
        result = self.run_fast(image_bytes(), "glued-date.png", lambda: FakeEngine(rows))
        meta = result["fast_metadata"]
        self.assertEqual((len(meta["roi_attempts"]), meta["stopped"]), (1, "header_complete"))
        self.assertTrue(meta["roi_attempts"][0]["evidence"]["issued_date"])
        # Evidence only: the line is returned exactly as read.
        self.assertIn("Hà Nội, ngày 07 tháng 04năm 2026", [line["text"] for line in result["pages"][0]["lines"]])

    def test_line_limit_without_header_does_not_grow_the_region(self):
        rows = [(f"Dòng không phải header {i}", 40, 20 + i * 5) for i in range(70)]
        result = self.run_fast(image_bytes(), "dense.png", lambda: FakeEngine(rows))
        meta = result["fast_metadata"]
        self.assertEqual((len(meta["roi_attempts"]), meta["stopped"]), (1, "line_limit_reached"))
        self.assertEqual(result["line_count"], fast.MAX_HEADER_LINES)

    def test_raw_stamp_overlap_line_is_never_rewritten(self):
        rows = header()
        rows[5] = ("ĐẾN 09/04/2026 — Sửa đổi, bổ sung nội dung", 100, 165)
        result = self.run_fast(image_bytes(), "stamp.png", lambda: FakeEngine(rows))
        self.assertIn(rows[5][0], result["text"])

    def test_native_subject_about_signatures_is_not_signer_metadata(self):
        rows = header()
        subject = "Triển khai ký số và quản lý chữ ký số."
        rows[5] = (subject, 100, 165)
        with patch.object(fast, "offline_engine", side_effect=AssertionError("genuine native header must not load OCR")):
            result = fast.extract_metadata_fast(pdf_bytes(rows), "native-signature-subject.pdf", Mock())
        line = next(line for line in result["pages"][0]["lines"] if line["text"] == subject)
        self.assertNotIn("metadata_excluded_reason", line)
        self.assertFalse(result["used_ocr"])

    def test_ocr_subject_about_signatures_is_not_signer_metadata(self):
        rows = header()
        subject = "V/v triển khai ký số và quản lý chữ ký số"
        rows[5] = (subject, 100, 165)
        result = self.run_fast(image_bytes(), "ocr-signature-subject.png", lambda: FakeEngine(rows))
        line = next(line for line in result["pages"][0]["lines"] if line["text"] == subject)
        self.assertNotIn("metadata_excluded_reason", line)
        self.assertIn(subject, result["text"])

    def test_png_jpg_and_exif_source_dimensions(self):
        for kind, extension in (("PNG", "png"), ("JPEG", "jpg")):
            result = self.run_fast(image_bytes(kind), "source." + extension, FakeEngine)
            self.assertEqual(result["source_page_count"], 1)
            self.assertEqual(result["pages"][0]["width"], 600)
        exif = Image.Exif(); exif[274] = 6
        result = self.run_fast(image_bytes("JPEG", (80, 160), exif), "rotated.jpg", lambda: FakeEngine([]))
        self.assertEqual((result["pages"][0]["width"], result["pages"][0]["height"]), (160, 80))

    def test_invalid_input_and_pixel_page_limits_fail_before_models(self):
        provider = Mock(side_effect=AssertionError("invalid upload must not load models"))
        invalid = [(b"%PDF-1.7 broken", "broken.pdf"), (pdf_bytes(pages=1001), "too_long.pdf"),
                   (b"not png", "false.png"), (b"\x89PNG\r\n\x1a\nBAD", "broken.png"),
                   (image_bytes(size=(4001, 3000)), "huge.png"), (b"x", "bad.exe")]
        for data, name in invalid:
            with self.subTest(name=name), self.assertRaises(ValueError):
                fast.extract_metadata_fast(data, name, provider)
        provider.assert_not_called()


class FastOfflineGuardTests(unittest.TestCase):
    def test_detector_pins_match_desktop_lock(self):
        root = Path(__file__).resolve().parents[4]
        lock = json.loads((root / "desktop/model_lock.json").read_text(encoding="utf-8"))
        self.assertEqual(fast.DETECTOR_FILES, lock["detector"]["files"])

    def test_missing_models_fail_before_sdk_import_or_provider(self):
        with patch.object(fast, "verify_frozen_onnx", side_effect=DemoConfigurationError("no weights")), \
             patch.object(fast, "_disable_downloads") as sdk:
            provider = Mock()
            with self.assertRaises(DemoConfigurationError): fast.offline_engine(provider)
        sdk.assert_not_called(); provider.assert_not_called()

    def test_missing_or_changed_detector_cannot_initialize_or_download(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"PADDLE_PDX_CACHE_HOME": folder}), \
             patch.object(fast, "verify_frozen_onnx"), patch.object(fast, "_disable_downloads") as sdk:
            provider = Mock()
            with self.assertRaisesRegex(DemoConfigurationError, "không tải"): fast.offline_engine(provider)
            target = Path(folder) / "official_models/PP-OCRv6_medium_det"; target.mkdir(parents=True)
            (target / "inference.json").write_bytes(b"wrong model")
            with self.assertRaises(DemoConfigurationError): fast.offline_engine(provider)
        sdk.assert_not_called(); provider.assert_not_called()

    def test_local_detector_passes_guard_before_cached_provider(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"PADDLE_PDX_CACHE_HOME": folder}), \
             patch.object(fast, "verify_frozen_onnx"), patch.object(fast, "_disable_downloads") as sdk:
            target = Path(folder) / "official_models/PP-OCRv6_medium_det"; target.mkdir(parents=True)
            (target / "fixture").write_bytes(b"local")
            with patch.object(fast, "DETECTOR_FILES", {"fixture": hashlib.sha256(b"local").hexdigest()}):
                self.assertEqual(fast.offline_engine(lambda: "cached instance"), "cached instance")
        sdk.assert_called_once()


class NativeTextOverOcrTests(unittest.TestCase):
    """A born-digital header OCRed because a value added at signing is missing from its text layer."""
    NATIVE = [("VĂN PHÒNG KIỂM THỬ", 40, 40), ("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", 300, 40),
              ("Số:        /VPCP-QA", 40, 90), ("Hà Nội, ngày      tháng      năm 2026", 300, 90),
              ("V/v kết thúc thực hiện Đề án kiểm thử", 40, 110), ("Kính gửi: Cơ quan QA", 200, 160)]
    OCR = {"Số:        /VPCP-QA": "Số: 10314/VPCP-QA", "Hà Nội, ngày      tháng      năm 2026": "Hà Nội, ngày 08 tháng 10 năm 2026",
           "V/v kết thúc thực hiện Đề án kiểm thử": "V/v kết thúc thưc hiên Đề án kiểm thử",
           "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM": "CÔNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM"}

    def run_on(self, payload):
        # The fake OCR reads each native line at its own place (2 px per point), with the readings above.
        with fitz.open(stream=payload, filetype="pdf") as pdf:
            native, _ = fast.native_lines(pdf[0])
        rows = [(self.OCR.get(line["text"], line["text"]), line["bbox"][0] * 2, line["bbox"][1] * 2) for line in native]
        engine = FakeEngine(rows)
        with patch.object(fast, "offline_engine", side_effect=lambda callback: callback()):
            return fast.extract_metadata_fast(payload, "digital.pdf", lambda: engine)

    def lines(self, result):
        return {line.get("ocr_text", line["text"]): line for line in result["pages"][0]["lines"]}

    def test_same_letters_take_the_pdf_text_and_inserted_values_keep_the_ocr(self):
        result = self.run_on(pdf_bytes(self.NATIVE, pages=2))
        self.assertTrue(result["used_ocr"])
        lines = self.lines(result)
        subject = lines["V/v kết thúc thưc hiên Đề án kiểm thử"]
        self.assertEqual((subject["text"], subject["text_source"]), ("V/v kết thúc thực hiện Đề án kiểm thử", "pdf_text"))
        self.assertEqual(lines["CÔNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM"]["text"], "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM")
        for reading in ("Số: 10314/VPCP-QA", "Hà Nội, ngày 08 tháng 10 năm 2026"):
            self.assertEqual(lines[reading]["text"], reading)
            self.assertNotIn("text_source", lines[reading])
        self.assertEqual(lines["VĂN PHÒNG KIỂM THỬ"]["text"], "VĂN PHÒNG KIỂM THỬ")
        self.assertNotIn("ocr_text", lines["VĂN PHÒNG KIỂM THỬ"])  # identical reading: nothing to record
        self.assertIn("ocr_lines_matched_to_pdf_text_layer", result["fast_metadata"]["reasons"])
        self.assertIn("V/v kết thúc thực hiện Đề án kiểm thử", result["text"])

    def test_a_scan_or_an_invisible_text_layer_is_never_trusted(self):
        def with_full_page_image(payload):
            pdf = fitz.open(stream=payload, filetype="pdf")
            image = io.BytesIO(); Image.new("L", (300, 400), 255).save(image, "PNG")
            pdf[0].insert_image(pdf[0].rect, stream=image.getvalue(), overlay=False)
            data = pdf.tobytes(); pdf.close()
            return data
        def invisible(payload_rows):
            pdf = fitz.open(); page = pdf.new_page(width=600, height=800)
            writer = fitz.TextWriter(page.rect)
            for text, x, y in payload_rows:
                writer.append((x, y), text, fontsize=9)
            writer.write_text(page, render_mode=3)
            pdf.new_page(width=600, height=800)
            data = pdf.tobytes(); pdf.close()
            return data
        for name, payload in (("scan", with_full_page_image(pdf_bytes(self.NATIVE, pages=2))), ("invisible", invisible(self.NATIVE))):
            with self.subTest(name):
                result = self.run_on(payload)
                subject = self.lines(result)["V/v kết thúc thưc hiên Đề án kiểm thử"]
                self.assertEqual(subject["text"], "V/v kết thúc thưc hiên Đề án kiểm thử")
                self.assertNotIn("text_source", subject)
                self.assertNotIn("ocr_lines_matched_to_pdf_text_layer", result["fast_metadata"]["reasons"])


class PrintedBlankTests(unittest.TestCase):
    """A number or day/month typed into a printed blank after signing, as its own text object (137-vbhn-bxd)."""
    HOST = [("BỘ KIỂM THỬ", 40, 40), ("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", 300, 40),
            ("Số:        /2026/VBHN-QA", 40, 90), ("Hà Nội, ngày      tháng      năm 2026", 300, 90),
            ("QUYẾT ĐỊNH", 260, 130), ("Về việc kiểm thử chỗ trống", 200, 145), ("Căn cứ Luật Kiểm thử;", 60, 190)]

    def payload(self, values):
        """values: (text, host text, which blank of that host, baseline shift); each is written as its own text
        object, centred on the blank's spaces as the PDF's own text layer places them."""
        pdf = fitz.open(); page = pdf.new_page(width=600, height=800)
        writer = fitz.TextWriter(page.rect)
        for text, x, y in self.HOST:
            writer.append((x, y), text, fontsize=9)
        writer.write_text(page)
        chars = {"".join(c["c"] for s in line["spans"] for c in s["chars"]): [c for s in line["spans"] for c in s["chars"]]
                 for block in page.get_text("rawdict")["blocks"] for line in block.get("lines", [])}
        values_writer = fitz.TextWriter(page.rect)
        for text, host, blank, shift in values:
            line_chars = chars[host]
            start, end = [(m.start(), m.end()) for m in re.finditer(r" {2,}", host)][blank]
            x0, x1 = line_chars[start]["bbox"][0], line_chars[end - 1]["bbox"][2]
            width = fitz.get_text_length(text, fontsize=9)
            values_writer.append(((x0 + x1 - width) / 2, line_chars[0]["origin"][1] + shift), text, fontsize=9)
        values_writer.write_text(page)
        pdf.new_page(width=600, height=800)
        data = pdf.tobytes(); pdf.close()
        return data

    def native(self, payload):
        with fitz.open(stream=payload, filetype="pdf") as pdf:
            return fast.native_lines(pdf[0])[0]

    def test_values_typed_into_the_blanks_are_read_in_place(self):
        number, date = "Số:        /2026/VBHN-QA", "Hà Nội, ngày      tháng      năm 2026"
        payload = self.payload([("137", number, 0, 2), ("08", date, 0, 0), ("10", date, 1, 2)])
        lines = {line["text"]: line for line in self.native(payload)}
        self.assertIn("Số: 137 /2026/VBHN-QA", lines)
        self.assertIn("Hà Nội, ngày 08 tháng 10 năm 2026", lines)
        self.assertEqual([item["text"] for item in lines["Hà Nội, ngày 08 tháng 10 năm 2026"]["filled_blanks"]], ["08", "10"])
        self.assertFalse({"137", "08", "10"} & set(lines))  # moved, not duplicated
        result = fast.extract_metadata_fast(payload, "blanks.pdf", lambda: self.fail("no OCR for a complete text layer"))
        self.assertFalse(result["used_ocr"])
        self.assertIn("Số: 137 /2026/VBHN-QA", result["text"])
        self.assertIn("pdf_values_filled_into_printed_blanks", result["fast_metadata"]["reasons"])

    def test_only_digits_inside_a_blank_on_the_same_row_are_moved(self):
        number, date = "Số:        /2026/VBHN-QA", "Hà Nội, ngày      tháng      năm 2026"
        cases = {"letters": [("AB", number, 0, 0)], "another row": [("137", number, 0, 14)]}
        for name, values in cases.items():
            with self.subTest(name):
                texts = [line["text"] for line in self.native(self.payload(values))]
                self.assertIn(number, texts)
                self.assertIn(values[0][0], texts)
                self.assertIn(date, texts)

    def test_ocr_lines_match_the_text_layer_regardless_of_quote_style(self):
        native = [{"text": "“Phát triển kiểm thử”", "bbox": [10, 10, 200, 20]}, {"text": "Số:     /QĐ-KT", "bbox": [10, 30, 200, 40]}]
        ocr = [{"text": "\"Phát triển kiểm thử\"", "bbox": [20, 20, 400, 40]}, {"text": "Số: 12/QĐ-KT", "bbox": [20, 60, 400, 80]}]
        merged = fast.native_text_over_ocr(ocr, native, 2)
        self.assertEqual((merged[0]["text"], merged[0]["text_source"]), ("“Phát triển kiểm thử”", "pdf_text"))
        self.assertEqual(merged[1]["text"], "Số: 12/QĐ-KT")  # a digit differs: the OCR reading stays


class HeaderPatternTests(unittest.TestCase):
    """Owner decisions 2026-11-10: the telegram title, and a date whose keyword touches its digits."""

    def test_issued_date_evidence_accepts_a_missing_space_between_a_keyword_and_its_digits(self):
        for text in ("Hà Nội, ngày 05 tháng 11 năm 2026", "Hà Nội, ngày 05 tháng 11năm 2026", "Hà Nội, ngày05 tháng11 năm2026",
                     "HÀ NỘI, NGÀY 5THÁNG 3NĂM 2026"):
            self.assertIsNotNone(fast.DATE.search(fast.match_text(text)), text)

    def test_issued_date_evidence_never_guesses_joins_or_splits_digits(self):
        for text in ("Hà Nội, ngày 05 tháng/1 năm 2026", "Hà Nội, ngày 0B tháng 11 năm 2026", "ngày 105 tháng 11 năm 2026",
                     "ngày 05 tháng 111 năm 2026", "ngày 0511 tháng năm 2026", "ngày 05 tháng 11 năm 20 26",
                     "Hà Nội, ngày      tháng      năm 2026"):
            self.assertIsNone(fast.DATE.search(fast.match_text(text)), text)

    def test_telegram_is_a_title_only_as_a_whole_line(self):
        self.assertTrue(fast.TITLE.fullmatch(fast.match_text("CÔNG ĐIỆN")))
        for text in ("CÔNG ĐIỆN KHẨN", "Về việc công điện", "THỦ TƯỚNG CHÍNH PHỦ điện:"):
            self.assertIsNone(fast.TITLE.fullmatch(fast.match_text(text)), text)

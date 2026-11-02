"""Synthetic model-free fast-mode contracts, not recognition/performance scores."""
import hashlib
import io
import json
import os
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
        fonts = [Path("C:/Windows/Fonts/segoeui.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
                 Path("/System/Library/Fonts/Supplemental/Arial.ttf"), Path("/Library/Fonts/Arial Unicode.ttf")]
        font = next((p for p in fonts if p.is_file()), None)
        if font is None:
            raise RuntimeError("A Unicode fixture font is required, as in the Electron synthetic-PDF CI")
        page.insert_font(fontname="qa", fontfile=str(font))
        for text, x, y in rows:
            page.insert_text((x, y), text, fontsize=9, fontname="qa")
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
        invalid = [(b"%PDF-1.7 broken", "broken.pdf"), (pdf_bytes(pages=7), "seven.pdf"),
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

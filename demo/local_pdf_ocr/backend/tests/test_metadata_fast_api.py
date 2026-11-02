"""Fast mode uses the existing API validation and sequential engine lifetime."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from demo.local_pdf_ocr.backend import app as api
from demo.local_pdf_ocr.backend import metadata_fast as fast
from demo.local_pdf_ocr.backend.contract import DemoConfigurationError
from test_metadata_fast import FakeEngine, image_bytes, pdf_bytes, header
from test_review_api import request


class FastApiTests(unittest.TestCase):
    def test_real_native_header_works_without_model(self):
        with patch.object(api, "get_engine", side_effect=DemoConfigurationError("no model")) as model:
            status, _, payload = request("/api/ocr", {"mode": "metadata_fast"}, "native.pdf", pdf_bytes(header()))
        self.assertEqual(status, 200, payload)
        result = json.loads(payload)
        self.assertFalse(result["used_ocr"])
        self.assertEqual(result["source_page_count"], 6)
        model.assert_not_called()

    def test_missing_models_do_not_return_signature_as_header(self):
        with patch.object(fast, "verify_frozen_onnx", side_effect=DemoConfigurationError("missing model")):
            status, _, payload = request("/api/ocr", {"mode": "metadata_fast"}, "signature.pdf",
                                         pdf_bytes([("Digitally signed by Portal", 150, 25)]))
        self.assertEqual(status, 503, payload)

    def test_fast_reuses_existing_lru_engine_and_reports_zero_warm_init(self):
        api.get_engine.cache_clear()
        try:
            with patch.object(api, "LocalOcrEngine", side_effect=FakeEngine) as constructor, \
                 patch.object(fast, "offline_engine", side_effect=lambda provider: provider()):
                first = request("/api/ocr", {"mode": "metadata_fast"}, "one.png", image_bytes())
                second = request("/api/ocr", {"mode": "metadata_fast"}, "two.png", image_bytes())
            self.assertEqual((first[0], second[0]), (200, 200))
            constructor.assert_called_once()
            self.assertGreater(json.loads(first[2])["timings_ms"]["model_init"], 0)
            self.assertEqual(json.loads(second[2])["timings_ms"]["model_init"], 0)
        finally:
            api.get_engine.cache_clear()

    def test_fast_shares_busy_lock_and_bad_inputs_stay_400(self):
        with patch.object(api, "_ocr_lock", SimpleNamespace(locked=lambda: True)), patch.object(api, "get_engine") as provider:
            status, _, _ = request("/api/ocr", {"mode": "metadata_fast"}, "busy.png", image_bytes())
        self.assertEqual(status, 429); provider.assert_not_called()
        with patch.object(api, "get_engine") as provider:
            status, _, _ = request("/api/ocr", {"mode": "metadata_fast"}, "bad.pdf", b"%PDF-BROKEN")
        self.assertEqual(status, 400); provider.assert_not_called()

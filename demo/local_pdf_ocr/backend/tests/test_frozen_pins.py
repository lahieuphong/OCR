"""The frozen VietOCR B1024 contract must not change silently.

Model-free: these tests check the pinned constants and defaults only. They do not
and cannot verify OCR output; that needs the private model files and the A0
baseline regression described in the README.
"""
import inspect
import unittest

from demo.local_pdf_ocr.backend import contract


class FrozenRecognizerPins(unittest.TestCase):
    def test_selected_checkpoint_and_graph_hashes(self):
        self.assertEqual(contract.CHECKPOINT_SHA256, "a2f9d737edca1b2d5d45231b34601a0eb573aafd0fde3202cf6d20601de3edb3")
        self.assertEqual(contract.EXPECTED_ENCODER_SHA256, "f20d629ad81171267b517794d9f23cbf48bd74d3b45c9747aa5a0930433c40f1")
        self.assertEqual(contract.EXPECTED_DECODER_SHA256, "67029da541d1904ab04d6de3aec0b0cbe9ab3d2efca15108f155b4c5e4abeb51")

    def test_model_files_are_read_from_the_untracked_models_folder(self):
        self.assertEqual(contract.MODEL_DIR.relative_to(contract.REPO_ROOT).as_posix(), "models/vietocr/onnx/exp_b_width1024")
        self.assertEqual(contract.WEIGHTS.relative_to(contract.REPO_ROOT).as_posix(),
                         "models/vietocr/finetuned/exp_b_width1024/weights.pth")

    def test_weights_are_required_by_default(self):
        default = inspect.signature(contract.verify_frozen_onnx).parameters["require_weights"].default
        self.assertIs(default, True)


class AppLimits(unittest.TestCase):
    def test_upload_limits(self):
        self.assertEqual(contract.MAX_UPLOAD_BYTES, 15 * 1024 * 1024)
        self.assertEqual(contract.MAX_PDF_PAGES, 6)
        self.assertEqual(contract.MAX_FAST_SOURCE_PAGES, 1000)
        self.assertEqual(contract.MAX_IMAGE_PIXELS, 12_000_000)
        self.assertEqual(contract.ACCEPTED_EXTENSIONS, frozenset({".pdf", ".png", ".jpg", ".jpeg"}))


if __name__ == "__main__":
    unittest.main()

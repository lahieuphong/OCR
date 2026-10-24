"""VIETDOC_MODEL_ROOT moves where the frozen model is read from, never what is accepted."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def run_contract(code: str, model_root: str | None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "VIETDOC_MODEL_ROOT"}
    if model_root is not None:
        env["VIETDOC_MODEL_ROOT"] = model_root
    return subprocess.run([sys.executable, "-B", "-c", "from demo.local_pdf_ocr.backend import contract as c\n" + code],
                          cwd=REPO_ROOT, env=env, capture_output=True, text=True, encoding="utf-8")


class ModelRootTests(unittest.TestCase):
    def test_default_is_repo_models(self):
        out = run_contract("print(c.MODEL_DIR); print(c.WEIGHTS)", None)
        self.assertEqual(out.returncode, 0, out.stderr)
        model_dir, weights = out.stdout.splitlines()
        self.assertEqual(Path(model_dir), REPO_ROOT / "models/vietocr/onnx/exp_b_width1024")
        self.assertEqual(Path(weights), REPO_ROOT / "models/vietocr/finetuned/exp_b_width1024/weights.pth")

    def test_external_root_keeps_layout(self):
        with tempfile.TemporaryDirectory() as root:
            out = run_contract("print(c.MODEL_DIR); print(c.WEIGHTS)", root)
            self.assertEqual(out.returncode, 0, out.stderr)
            model_dir, weights = out.stdout.splitlines()
            self.assertEqual(Path(model_dir), Path(root) / "vietocr/onnx/exp_b_width1024")
            self.assertEqual(Path(weights), Path(root) / "vietocr/finetuned/exp_b_width1024/weights.pth")

    def test_relative_root_is_refused(self):
        out = run_contract("print(c.MODEL_DIR)", "models")
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("VIETDOC_MODEL_ROOT must be an absolute path", out.stderr)

    def test_empty_external_root_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            out = run_contract("c.verify_frozen_onnx(require_weights=True)", root)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("Missing/invalid ONNX files", out.stderr)

    def test_unknown_files_in_external_root_are_rejected(self):
        # Right file names, wrong bits: the SHA-256 checks still decide.
        with tempfile.TemporaryDirectory() as root:
            onnx = Path(root) / "vietocr/onnx/exp_b_width1024"
            onnx.mkdir(parents=True)
            (onnx / "encoder.onnx").write_bytes(b"not the frozen encoder")
            (onnx / "decoder_step.onnx").write_bytes(b"not the frozen decoder")
            (onnx / "parity_full.json").write_text("{}", encoding="utf-8")
            out = run_contract("import json\n"
                               "meta = {'checkpoint_sha256': c.CHECKPOINT_SHA256, 'encoder_sha256': c.EXPECTED_ENCODER_SHA256,"
                               " 'decoder_sha256': c.EXPECTED_DECODER_SHA256, 'image_height': 32, 'image_min_width': 32,"
                               " 'image_max_width': 1024, 'decoder_max_seq_length': 128, 'batch_size': 1,"
                               " 'status': 'EXPORTED_NOT_YET_PARITY_VERIFIED'}\n"
                               "(c.MODEL_DIR / 'metadata.json').write_text(json.dumps(meta), encoding='utf-8')\n"
                               "c.verify_frozen_onnx(require_weights=True)", root)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("SHA256 mismatch", out.stderr)


if __name__ == "__main__":
    unittest.main()

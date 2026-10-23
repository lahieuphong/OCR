"""Tests for packaging/ci/scan_bundle.py on throw-away folders (no real build needed).

Secret-looking strings are assembled at run time so this file itself never matches the tracked-file rules.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("scan_bundle.py")


def run(root, *extra):
    out = tempfile.mkdtemp()
    proc = subprocess.run([sys.executable, str(SCRIPT), str(root), out, *extra], capture_output=True, text=True)
    return proc.returncode, json.loads(Path(out, "scan.json").read_text(encoding="utf-8")), Path(out, "manifest.tsv")


def write(root, rel, data=b"x"):
    p = Path(root, rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))


class ScanBundleTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        write(self.root, "VietDoc OCR.exe", b"MZ" + b"\0" * 64)
        write(self.root, "resources/app.asar", b"asar")
        write(self.root, "resources/model_lock.json", json.dumps({"vietocr": {"encoder_sha256": "f" * 64}}))
        write(self.root, "resources/backend/vietdoc-backend/_internal/certifi/cacert.pem", "-----BEGIN CERTIFICATE-----")

    def reasons(self, summary):
        return sorted({f["reason"] for f in summary["findings"]})

    def test_clean_build_passes_and_writes_a_complete_manifest(self):
        code, summary, manifest = run(self.root)
        self.assertEqual(code, 0, summary)
        self.assertEqual(summary["result"], "PASS")
        rows = manifest.read_text(encoding="utf-8").splitlines()
        self.assertEqual(rows[0], "path\tsize\tsha256")
        self.assertEqual(len(rows) - 1, summary["files"])
        self.assertTrue(all(len(r.split("\t")[2]) == 64 for r in rows[1:]))

    def test_models_documents_exports_config_and_logs_fail(self):
        for rel in ["resources/encoder.onnx", "resources/weights.pth", "resources/inference.pdiparams", "doc.pdf",
                    "x/10333_vietocr_ocr.json", "x/desktop.config.json", "x/backend.log", "x/smoke_report.json",
                    "x/.env", "x/signing.pfx", "x/site/direct_url.json", "x/dump.jsonl"]:
            write(self.root, rel)
        code, summary, _ = run(self.root)
        self.assertEqual(code, 1)
        found = {f["path"] for f in summary["findings"]}
        self.assertEqual(len(found), 12, summary["findings"])

    def test_private_key_and_tokens_fail_but_public_ca_bundle_passes(self):
        write(self.root, "a.pem", "-----BEGIN " + "RSA PRIVATE KEY-----\nabc")
        write(self.root, "b.js", "const t = 'gh" + "p_" + "A" * 36 + "';")
        write(self.root, "c.txt", "key=" + "AKIA" + "ABCDEFGHIJKLMNOP" + "\n")
        code, summary, _ = run(self.root)
        self.assertEqual(code, 1)
        self.assertEqual(self.reasons(summary), ["AWS access key", "GitHub token", "private key block"])
        self.assertNotIn("cacert.pem", json.dumps(summary["findings"]))

    def test_aws_pattern_inside_a_base64_blob_is_not_a_credential(self):
        write(self.root, "blob.bin", b"\0gFBgAEKAKI" + b"AKIA" + b"SAEKAKMAUEBQQIQ3" + b"RMMMQsgBEGYAW\0")
        code, summary, _ = run(self.root)
        self.assertEqual(code, 0, summary)

    def test_machine_paths_fail_in_utf8_utf16_and_either_slash(self):
        write(self.root, "p1.pyc", b"\0" + "D:\\a\\OCR\\demo\\x.py".encode("utf-8"))
        write(self.root, "p2.dll", "D:/a/OCR/desktop".encode("utf-16-le"))
        code, summary, _ = run(self.root, "--forbid-string", "D:\\a\\OCR")
        self.assertEqual(code, 1)
        self.assertEqual({f["path"] for f in summary["findings"]}, {"p1.pyc", "p2.dll"})

    def test_model_lock_with_a_path_fails(self):
        write(self.root, "resources/model_lock.json", json.dumps({"root": "C:\\Users\\u\\models"}))
        code, summary, _ = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("model_lock.json contains a path", self.reasons(summary))


if __name__ == "__main__":
    unittest.main()

"""Installer payloads must contain exactly the checked release bytes, including no extra models."""
from pathlib import Path
import shutil
import tempfile
import unittest

from check_installer_payload import verify


class InstallerPayloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.checked = Path(self.tmp.name) / "checked"
        self.extracted = Path(self.tmp.name) / "extracted"
        for name in ("VietDoc OCR Test.exe", "resources/app.asar", "resources/backend/vietdoc-backend/vietdoc-backend.exe"):
            file = self.checked / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b"known checked app bytes")
        shutil.copytree(self.checked, self.extracted)

    def report(self):
        return verify(self.checked, self.extracted, "VietDoc OCR Test.exe")

    def test_identical_installer_payload_passes(self):
        self.assertEqual(self.report()["result"], "PASS")

    def test_modified_ui_or_backend_fails(self):
        (self.extracted / "resources/app.asar").write_bytes(b"replaced UI")
        report = self.report()
        self.assertEqual(report["result"], "FAIL")
        self.assertEqual(report["changed"], ["resources/app.asar"])

    def test_added_model_or_removed_file_fails(self):
        (self.extracted / "resources/model.onnx").write_bytes(b"unexpected model")
        (self.extracted / "VietDoc OCR Test.exe").unlink()
        report = self.report()
        self.assertEqual(report["result"], "FAIL")
        self.assertEqual(report["extra"], ["resources/model.onnx"])
        self.assertEqual(report["missing"], ["VietDoc OCR Test.exe"])

    def test_two_empty_folders_cannot_pass(self):
        shutil.rmtree(self.checked)
        shutil.rmtree(self.extracted)
        self.checked.mkdir()
        self.extracted.mkdir()
        self.assertEqual(self.report()["result"], "FAIL")


if __name__ == "__main__":
    unittest.main()

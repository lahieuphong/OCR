"""Tests for the release build's own logic (names, gates, staging, path budget, Portable ZIP) without a real build."""
import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_release  # noqa: E402
import portable_zip  # noqa: E402


def write(root: Path, rel: str, data: bytes = b"x") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class NamesAndGatesTest(unittest.TestCase):
    def test_internal_names_say_internal_and_public_names_match_the_release_page(self):
        self.assertEqual(build_release.release_names("0.1.0", "internal"),
                         {"setup": "VietDoc-OCR-v0.1.0-INTERNAL-Windows-x64-Setup.exe",
                          "portable": "VietDoc-OCR-v0.1.0-INTERNAL-Windows-x64-Portable.zip"})
        self.assertEqual(build_release.release_names("0.1.0-rc.1", "public"),
                         {"setup": "VietDoc-OCR-v0.1.0-rc.1-Windows-x64-Setup.exe",
                          "portable": "VietDoc-OCR-v0.1.0-rc.1-Windows-x64-Portable.zip"})
        for version, channel in (("0.1", "internal"), ("0.1.0 ", "public"), ("0.1.0", "beta")):
            with self.assertRaises(build_release.BuildError):
                build_release.release_names(version, channel)

    def test_config_names_follow_the_electron_builder_files(self):
        desktop = Path(build_release.DESKTOP)
        for name in (*build_release.CONFIGS.values(), build_release.SMOKE_CONFIG):
            self.assertTrue((desktop / name).is_file(), name)
        text = (desktop / "electron-builder.release.yml").read_text(encoding="utf-8")
        self.assertIn("artifactName: VietDoc-OCR-v${version}-INTERNAL-Windows-${arch}-Setup.${ext}", text)
        public = (desktop / "electron-builder.release-public.yml").read_text(encoding="utf-8")
        self.assertIn("artifactName: VietDoc-OCR-v${version}-Windows-${arch}-Setup.${ext}", public)
        self.assertIn("license: build-resources/PUBLIC_LICENSE.txt", public)

    def test_output_folder_must_be_absolute_outside_the_checkout_and_empty(self):
        repo = Path(tempfile.mkdtemp())
        with self.assertRaises(build_release.BuildError):
            build_release.check_out_dir(Path("relative"), repo)
        with self.assertRaises(build_release.BuildError):
            build_release.check_out_dir(repo / "out", repo)
        with self.assertRaises(build_release.BuildError):
            build_release.check_out_dir(repo.parent, repo)
        out = Path(tempfile.mkdtemp())
        build_release.check_out_dir(out, repo)
        write(out, "old.txt")
        with self.assertRaises(build_release.BuildError):
            build_release.check_out_dir(out, repo)

    def test_public_builds_need_a_commit_and_the_approved_licence_text(self):
        licence = Path(tempfile.mkdtemp(), "PUBLIC_LICENSE.txt")
        gate = build_release.channel_gate
        gate("internal", dirty=False, allow_dirty=False, public_license=licence)
        gate("internal", dirty=True, allow_dirty=True, public_license=licence)
        with self.assertRaises(build_release.BuildError):
            gate("internal", dirty=True, allow_dirty=False, public_license=licence)
        with self.assertRaisesRegex(build_release.BuildError, "BLOCKED"):
            gate("public", dirty=False, allow_dirty=False, public_license=licence)
        licence.write_text("approved", encoding="utf-8")
        gate("public", dirty=False, allow_dirty=False, public_license=licence)
        with self.assertRaises(build_release.BuildError):
            gate("public", dirty=True, allow_dirty=True, public_license=licence)

    def test_public_builds_build_their_own_backend_and_need_the_licence_inputs(self):
        base = Path(tempfile.mkdtemp())
        licence, card, vietocr = (write(base, name, b"x") for name in ("PUBLIC_LICENSE.txt", "README.md", "LICENSE"))
        gate = build_release.channel_gate
        gate("public", False, False, licence, licence_inputs=(vietocr, card))
        with self.assertRaisesRegex(build_release.BuildError, "reuse-backend"):
            gate("public", False, False, licence, reuse_backend=True, licence_inputs=(vietocr, card))
        with self.assertRaisesRegex(build_release.BuildError, "vietocr-license"):
            gate("public", False, False, licence, licence_inputs=(None, card))
        gate("internal", False, False, licence, reuse_backend=True, licence_inputs=(None, None))

    def test_the_backend_must_carry_the_utf8_code_page(self):
        base = Path(tempfile.mkdtemp())
        good = write(base, "good.exe", b"MZ..<activeCodePage xmlns=\"http://schemas.microsoft.com/SMI/2019/WindowsSettings\">UTF-8</activeCodePage>..")
        bad = write(base, "bad.exe", b"MZ..<longPathAware>true</longPathAware>..")
        self.assertTrue(build_release.has_utf8_code_page(good))
        self.assertFalse(build_release.has_utf8_code_page(bad))


class StagingTest(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.mkdtemp())
        self.models, self.paddlex, self.staging = base / "models", base / "paddlex", base / "staging"
        files = {"models/vietocr/onnx/exp_b_width1024/encoder.onnx": b"enc",
                 "models/vietocr/onnx/exp_b_width1024/decoder_step.onnx": b"dec",
                 "models/vietocr/finetuned/exp_b_width1024/weights.pth": b"pth",
                 "paddlex/official_models/PP-OCRv6_medium_det/inference.json": b"{}",
                 "paddlex/official_models/PP-OCRv6_medium_det/inference.pdiparams": b"det",
                 "paddlex/official_models/PP-OCRv6_medium_det/inference.yml": b"yml"}
        for rel, data in files.items():
            write(base, rel, data)
        write(base, "models/vietocr/onnx/exp_b_width1024/metadata.json", b"{}")
        write(base, "models/vietocr/onnx/exp_b_width1024/parity_full.json", b"{}")
        write(base, "models/vietocr/finetuned/exp_b_width1024/checkpoint.pth", b"training only")
        digest = lambda rel: hashlib.sha256(files[rel]).hexdigest()
        lock = {"recognizer": {"encoder_sha256": digest("models/vietocr/onnx/exp_b_width1024/encoder.onnx"),
                               "decoder_sha256": digest("models/vietocr/onnx/exp_b_width1024/decoder_step.onnx"),
                               "checkpoint_sha256": digest("models/vietocr/finetuned/exp_b_width1024/weights.pth")},
                "detector": {"model_name": "PP-OCRv6_medium_det", "files": {
                    n: digest(f"paddlex/official_models/PP-OCRv6_medium_det/{n}")
                    for n in ("inference.json", "inference.pdiparams", "inference.yml")}}}
        self.lock = write(base, "model_lock.json", json.dumps(lock).encode())

    def test_stages_exactly_the_files_ocr_needs(self):
        staged = build_release.stage_models(self.models, self.paddlex, self.lock, self.staging)
        found = sorted(p.relative_to(self.staging).as_posix() for p in self.staging.rglob("*") if p.is_file())
        self.assertEqual(found, sorted(staged))
        self.assertEqual(len(found), 8)
        self.assertNotIn("models/vietocr/finetuned/exp_b_width1024/checkpoint.pth", found)
        self.assertEqual(sum(info["locked"] for info in staged.values()), 6)

    def test_a_changed_or_missing_model_stops_the_build(self):
        write(self.models, "vietocr/onnx/exp_b_width1024/encoder.onnx", b"other")
        with self.assertRaises(build_release.BuildError):
            build_release.stage_models(self.models, self.paddlex, self.lock, self.staging)
        (self.models / "vietocr/onnx/exp_b_width1024/encoder.onnx").unlink()
        with self.assertRaises(build_release.BuildError):
            build_release.stage_models(self.models, self.paddlex, self.lock, Path(tempfile.mkdtemp()))

    def test_locked_paths_match_the_bundle_scanner(self):
        sys.path.insert(0, str(Path(build_release.REPO) / "packaging" / "ci"))
        import scan_bundle
        staged = {"resources/" + rel for rel in build_release.locked_model_files(Path(build_release.DESKTOP) / "model_lock.json")}
        self.assertEqual(staged, set(scan_bundle.locked_models(str(Path(build_release.DESKTOP) / "model_lock.json"))))


class NodeModulesTest(unittest.TestCase):
    def test_installed_versions_must_match_the_lockfile(self):
        folder = Path(tempfile.mkdtemp())
        write(folder, "package-lock.json", json.dumps({"packages": {
            "": {}, "node_modules/a": {"version": "1.0.0"}, "node_modules/opt": {"version": "1.0.0", "optional": True}}}).encode())
        write(folder, "node_modules/a/package.json", json.dumps({"version": "1.0.0"}).encode())
        self.assertEqual(build_release.check_node_modules(folder), 2)
        write(folder, "node_modules/a/package.json", json.dumps({"version": "1.0.1"}).encode())
        with self.assertRaises(build_release.BuildError):
            build_release.check_node_modules(folder)


class PathBudgetTest(unittest.TestCase):
    def test_reports_the_margin_for_install_and_extract_locations(self):
        app = Path(tempfile.mkdtemp())
        write(app, "resources/" + "d" * 40 + "/f.txt")
        budget = build_release.path_budget(app, "VietDoc-OCR-v0.1.0-Windows-x64-Portable")
        self.assertEqual(budget["result"], "PASS")
        self.assertEqual(budget["longest_chars"], len("resources\\" + "d" * 40 + "\\f.txt"))
        self.assertGreater(budget["setup"]["margin"], budget["portable"]["margin"])
        write(app, "resources/" + "e" * 160 + ".txt")   # creatable here, too long under a Downloads extract
        budget = build_release.path_budget(app, "VietDoc-OCR-v0.1.0-Windows-x64-Portable")
        self.assertEqual((budget["result"], budget["setup"]["margin"] >= 0), ("FAIL", True))


class PortableZipTest(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.mkdtemp())
        self.app = base / "app"
        write(self.app, "VietDoc OCR.exe", b"MZ")
        write(self.app, "resources/app.asar", b"asar")
        (self.app / "resources" / "empty").mkdir()
        self.guide = write(base, "guide.txt", "Đọc trước".encode("utf-8"))
        self.zip = base / "VietDoc-OCR-v0.1.0-INTERNAL-Windows-x64-Portable.zip"

    def test_zip_holds_the_app_the_data_folder_and_the_guide(self):
        portable_zip.make(self.app, self.zip, {"DOC_TRUOC_KHI_CHAY.txt": self.guide})
        result = portable_zip.verify(self.zip, self.app, {"DOC_TRUOC_KHI_CHAY.txt": self.guide})
        self.assertEqual(result["result"], "PASS", result)
        with zipfile.ZipFile(self.zip) as archive:
            names = sorted(archive.namelist())
        self.assertEqual(names, ["DOC_TRUOC_KHI_CHAY.txt", "VietDoc OCR Data/", "VietDoc OCR/VietDoc OCR.exe",
                                 "VietDoc OCR/resources/app.asar", "VietDoc OCR/resources/empty/"])
        self.assertFalse(self.zip.with_name(self.zip.name + ".partial").exists())
        with self.assertRaises(FileExistsError):
            portable_zip.make(self.app, self.zip, {})

    def test_verify_fails_when_the_app_changed_or_the_zip_has_more(self):
        portable_zip.make(self.app, self.zip, {})
        write(self.app, "resources/app.asar", b"other")
        result = portable_zip.verify(self.zip, self.app, {})
        self.assertEqual((result["result"], result["changed"]), ("FAIL", ["VietDoc OCR/resources/app.asar"]))
        with zipfile.ZipFile(self.zip, "a") as archive:
            archive.writestr("../escape.txt", "x")
        result = portable_zip.verify(self.zip, self.app, {})
        self.assertEqual(result["unsafe_names"], ["../escape.txt"])

    def test_verify_compares_with_the_scanned_manifest(self):
        scanned = portable_zip.file_manifest(self.app)
        portable_zip.make(self.app, self.zip, {})
        self.assertEqual(portable_zip.verify(self.zip, self.app, {}, expected=scanned)["result"], "PASS")
        write(self.app, "resources/app.asar", b"changed after the scan")
        result = portable_zip.verify(self.zip, self.app, {}, expected=scanned)
        self.assertEqual((result["result"], result["changed"]), ("FAIL", ["resources/app.asar"]))

    def test_extras_must_be_plain_names(self):
        with self.assertRaises(ValueError):
            portable_zip.make(self.app, self.zip, {"VietDoc OCR/x.txt": self.guide})


if __name__ == "__main__":
    unittest.main()

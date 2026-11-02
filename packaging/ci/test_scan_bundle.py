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

    def test_fast_partial_and_hybrid_downloads_cannot_ship_or_be_tracked(self):
        import importlib.util

        root = Path(__file__).resolve().parents[2]
        spec = importlib.util.spec_from_file_location("tracked_file_gate", root / ".github/scripts/check_tracked_files.py")
        tracked = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tracked)
        downloads = ["downloads/document_metadata_fast_partial.json", "downloads/document_metadata_fast_partial.txt",
                     "downloads/document_metadata_fast_metadata.json", "downloads/document_hybrid_h1.txt"]
        for rel in downloads:
            write(self.root, rel, "private text")
            self.assertIn("app OCR export", tracked.path_problems(rel))
        code, summary, _ = run(self.root)
        self.assertEqual(code, 1)
        self.assertEqual({item["path"] for item in summary["findings"]}, set(downloads))
        self.assertEqual(self.reasons(summary), ["OCR export"])

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

    def test_upstream_wheel_profile_acceptance_needs_identical_bytes(self):
        rel = "resources/backend/vietdoc-backend/_internal/bidi/bidi.cp312-win_amd64.pyd"
        wheel_suffix = "bidi/bidi.cp312-win_amd64.pyd"
        profile = "C:" + chr(92) + "Users" + chr(92) + "runneradmin"
        payload = b"MZ" + profile.encode() + b" benign PE debug content"
        write(self.root, rel, payload)
        with tempfile.TemporaryDirectory() as wheels:
            write(wheels, wheel_suffix, payload)
            args = ("--forbid-string", profile, "--verified-wheel-root", wheels,
                    "--verified-wheel-profile", profile)
            code, result, _ = run(self.root, *args)
            self.assertEqual(code, 0, result)
            self.assertEqual(result["findings"], [])
            self.assertEqual([w["path"] for w in result["verified_wheel_warnings"]], [rel])

            write(self.root, rel, payload + b" tampered")
            code, result, _ = run(self.root, *args)
            self.assertEqual(code, 1)
            self.assertIn(rel, {f["path"] for f in result["findings"]})

            write(self.root, rel, payload)
            write(self.root, "resources/app.asar", profile)
            code, result, _ = run(self.root, *args)
            self.assertEqual(code, 1)
            self.assertIn("resources/app.asar", {f["path"] for f in result["findings"]})

            code, result, _ = run(self.root, "--forbid-string", profile)
            self.assertEqual(code, 1)
            self.assertIn(rel, {f["path"] for f in result["findings"]})

    def test_verified_wheel_still_checks_secrets_and_other_paths(self):
        rel = "resources/backend/vietdoc-backend/_internal/shapely/_geos.cp312-win_amd64.pyd"
        profile = "C:" + chr(92) + "Users" + chr(92) + "runneradmin"
        checkout = "D:" + chr(92) + "a" + chr(92) + "OCR"
        token = "gh" + "p_" + "A" * 36
        payload = ("MZ " + profile + " " + checkout + " " + token).encode()
        write(self.root, rel, payload)
        with tempfile.TemporaryDirectory() as wheels:
            write(wheels, "shapely/_geos.cp312-win_amd64.pyd", payload)
            code, result, _ = run(self.root, "--forbid-string", profile, "--forbid-string", checkout,
                                  "--verified-wheel-root", wheels, "--verified-wheel-profile", profile)
            self.assertEqual(code, 1)
            self.assertIn("GitHub token", {f["reason"] for f in result["findings"]})
            self.assertTrue(any(f["reason"].startswith("machine path") for f in result["findings"]))

    def directory_link(self, link, target):
        if os.name == "nt":
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            link.symlink_to(target, target_is_directory=True)

    def test_macos_framework_directory_alias_requires_explicit_allowance(self):
        with tempfile.TemporaryDirectory() as app:
            real = Path(app, "Contents", "Frameworks", "Electron Framework.framework", "Versions", "A")
            real.mkdir(parents=True)
            (real / "Electron Framework").write_bytes(b"Mach-O")
            current = real.with_name("Current")
            self.directory_link(current, real)
            code, summary, _ = run(app)
            self.assertEqual(code, 1, summary)
            self.assertIn("symbolic link or junction", self.reasons(summary))
            code, summary, manifest = run(app, "--allow-internal-symlinks")
            self.assertEqual(code, 0, summary)
            self.assertEqual(summary["files"], 1)
            self.assertNotIn("Current/", manifest.read_text(encoding="utf-8"))
            # Content is scanned through the real directory, even when an alias is permitted.
            (real / "private.onnx").write_bytes(b"model")
            code, summary, _ = run(app, "--allow-internal-symlinks")
            self.assertEqual(code, 1, summary)
            self.assertIn("model weights or checkpoint", self.reasons(summary))

    def test_macos_directory_alias_cannot_escape_the_app(self):
        with tempfile.TemporaryDirectory() as app, tempfile.TemporaryDirectory() as outside:
            self.directory_link(Path(app, "Frameworks"), Path(outside))
            code, summary, _ = run(app, "--allow-internal-symlinks")
            self.assertEqual(code, 1, summary)
            self.assertIn("symbolic link escapes the app", self.reasons(summary))

    def test_posix_file_aliases_cannot_hide_models_or_escape_the_app(self):
        # Windows CI checks directory junctions above; POSIX CI additionally exercises file symlinks,
        # which require an administrator or Developer Mode on Windows.
        if os.name == "nt":
            return
        with tempfile.TemporaryDirectory() as app, tempfile.TemporaryDirectory() as outside:
            root = Path(app)
            (root / "payload.bin").write_bytes(b"model")
            (root / "encoder.onnx").symlink_to("payload.bin")
            (Path(outside) / "secret.txt").write_bytes(b"private")
            (root / "escape.txt").symlink_to(Path(outside) / "secret.txt")
            (root / "missing").symlink_to("no-such-file")
            (root / "loop").symlink_to("loop")
            code, summary, _ = run(app, "--allow-internal-symlinks")
            self.assertEqual(code, 1, summary)
            reasons = self.reasons(summary)
            self.assertIn("model weights or checkpoint", reasons)
            self.assertIn("symbolic link escapes the app", reasons)
            self.assertIn("broken or cyclic symbolic link", reasons)

    def test_mac_crypto_header_constants_require_exact_path_and_no_key_body(self):
        library = "Contents/Resources/backend/vietdoc-backend/_internal/cv2/.dylibs/libmbedcrypto.3.5.1.dylib"
        header = b"-----BEGIN " + b"RSA PRIVATE KEY-----"
        literal = bytes.fromhex("cffaedfe0c000001") + b"\0" + header + b"\n\0"
        write(self.root, library, literal)
        code, summary, _ = run(self.root)
        self.assertEqual(code, 0, summary)
        self.assertEqual(summary["public_crypto_warnings"][0]["matches"], 1)
        # MH_MAGIC_64 alone also describes Intel; require CPU_TYPE_ARM64 as well.
        write(self.root, library, bytes.fromhex("cffaedfe07000001") + literal[8:])
        code, summary, _ = run(self.root)
        self.assertEqual(code, 1, summary)
        self.assertIn("private key block", self.reasons(summary))
        # Known parser constants never exempt the rest of their library.
        write(self.root, library, literal + header + b"\nnot-a-public-key\n")
        code, summary, _ = run(self.root)
        self.assertEqual(code, 1, summary)
        self.assertIn("private key block", self.reasons(summary))
        write(self.root, library, literal)
        write(self.root, "Contents/Resources/unknown.dylib", literal)
        code, summary, _ = run(self.root)
        self.assertEqual(code, 1, summary)
        self.assertIn("Contents/Resources/unknown.dylib", {f["path"] for f in summary["findings"]})

    def test_mac_gnutls_accepts_only_exact_public_self_test_keys(self):
        # Public GnuTLS 3.8.5 gost01 known-answer fixture, assembled so the source
        # itself does not contain a PEM block (keys are never sourced from user material).
        header = b"-----BEGIN " + b"PRIVATE KEY-----\n"
        footer = b"-----END " + b"PRIVATE KEY-----\n"
        fixture = (header + b"MEUCAQAwHAYGKoUDAgITMBIGByqFAwICIwEGByqFAwICHgEEIgQgdNfuHGmmTdPm\n"
                   + b"p5dAa3ea9UYxpdYQPP9lbDwzQwG2bJM=\n" + footer)
        library = "Contents/Resources/backend/vietdoc-backend/_internal/libgnutls.30.dylib"
        payload = bytes.fromhex("cffaedfe0c000001") + b"\0" + fixture + b"\0"
        write(self.root, library, payload)
        code, summary, _ = run(self.root)
        self.assertEqual(code, 0, summary)
        self.assertEqual(summary["public_crypto_warnings"][0]["matches"], 1)
        # A real/different key appended beside the known public fixture must still fail.
        write(self.root, library, payload + fixture.replace(b"MEUC", b"NEUC") + b"\0")
        code, summary, _ = run(self.root)
        self.assertEqual(code, 1, summary)
        self.assertIn("private key block", self.reasons(summary))
        # Tokens remain forbidden even in a library containing a known-answer key.
        write(self.root, library, payload + b"gh" + b"p_" + b"A" * 36)
        code, summary, _ = run(self.root)
        self.assertEqual(code, 1, summary)
        self.assertIn("GitHub token", self.reasons(summary))
        # The same bytes outside the specific Mach-O library are not exempted.
        write(self.root, library, b"not Mach-O\0" + fixture + b"\0")
        code, summary, _ = run(self.root)
        self.assertEqual(code, 1, summary)
        self.assertIn("private key block", self.reasons(summary))

    def test_model_lock_with_a_path_fails(self):
        write(self.root, "resources/model_lock.json", json.dumps({"root": "C:\\Users\\u\\models"}))
        code, summary, _ = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("model_lock.json contains a path", self.reasons(summary))


if __name__ == "__main__":
    unittest.main()

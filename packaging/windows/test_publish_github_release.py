"""Tests for the checks and the release page of publish_github_release.py (no network, no git writes)."""
import base64
import hashlib
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_release  # noqa: E402
import publish_github_release as publish  # noqa: E402

HEAD = "9" * 40
REPO_NOTES = Path(__file__).resolve().parents[2] / "release" / "windows" / "RELEASE_NOTES_v0.1.1.md"


def release_folder(channel="public", source=HEAD, version="0.1.0") -> Path:
    folder = Path(tempfile.mkdtemp()) / "release"
    folder.mkdir()
    names = build_release.release_names(version, "public")
    (folder / names["setup"]).write_bytes(b"MZ setup")
    (folder / names["portable"]).write_bytes(b"PK portable")
    (folder / (names["setup"] + ".blockmap")).write_bytes(b"blockmap")
    sums = "".join(f"{hashlib.sha256((folder / n).read_bytes()).hexdigest()}  {n}\n" for n in (names["setup"], names["portable"]))
    (folder / "SHA256SUMS.txt").write_text(sums, encoding="utf-8")
    sha512 = base64.b64encode(hashlib.sha512(b"MZ setup").digest()).decode()
    (folder / "latest.yml").write_text(f"version: {version}\nfiles:\n  - url: {names['setup']}\npath: {names['setup']}\n"
                                       f"sha512: {sha512}\nreleaseDate: '2026-11-11T00:00:00.000Z'\n", encoding="utf-8")
    (folder / "BUILD_INFO.txt").write_text(f"VietDoc OCR {version} - Windows x64\nChannel: {channel}\nSource: {source}\n",
                                           encoding="utf-8")
    (folder / "THIRD_PARTY_NOTICES.txt").write_text("notices", encoding="utf-8")
    return folder


class PublishChecksTest(unittest.TestCase):
    def test_a_checked_public_build_of_head_passes(self):
        folder = release_folder()
        self.assertEqual(publish.check_folder(folder, HEAD)["version"], "0.1.0")
        self.assertEqual([p.name for p in publish.assets(folder, "0.1.0")][:4],
                         ["VietDoc-OCR-v0.1.0-Windows-x64-Setup.exe", "VietDoc-OCR-v0.1.0-Windows-x64-Setup.exe.blockmap",
                          "VietDoc-OCR-v0.1.0-Windows-x64-Portable.zip", "latest.yml"])

    def test_internal_dirty_or_other_commit_builds_are_refused(self):
        for folder in (release_folder(channel="INTERNAL TEST BUILD - not for distribution"),
                       release_folder(source=HEAD + " + uncommitted changes (working tree sha256 x)"),
                       release_folder(source="1" * 40)):
            with self.assertRaises(build_release.BuildError):
                publish.check_folder(folder, HEAD)

    def test_a_changed_file_or_a_stale_latest_yml_is_refused(self):
        folder = release_folder()
        (folder / "VietDoc-OCR-v0.1.0-Windows-x64-Portable.zip").write_bytes(b"changed")
        with self.assertRaisesRegex(build_release.BuildError, "SHA256SUMS"):
            publish.check_folder(folder, HEAD)
        folder = release_folder()
        text = (folder / "latest.yml").read_text(encoding="utf-8").replace("version: 0.1.0", "version: 0.0.9")
        (folder / "latest.yml").write_text(text, encoding="utf-8")
        with self.assertRaisesRegex(build_release.BuildError, "latest.yml"):
            publish.check_folder(folder, HEAD)

    def test_the_page_has_the_downloads_the_warning_and_the_source(self):
        page = publish.body("0.1.0", HEAD, "lahieuphong/OCR")
        for text in ("## Tải về", "**Setup — khuyên dùng:** `VietDoc-OCR-v0.1.0-Windows-x64-Setup.exe`",
                     "tự cập nhật từ GitHub Releases", "**Portable — không cần cài:** `VietDoc-OCR-v0.1.0-Windows-x64-Portable.zip`",
                     "không tự cập nhật", "chưa được ký số", "SHA256SUMS.txt", f"commit/{HEAD}",
                     "blob/v0.1.0/release/windows/HUONG_DAN_CAI_DAT.md", "**Full Changelog**"):
            self.assertIn(text, page)
        self.assertNotIn("## Có gì mới", page)

    def test_the_page_starts_with_the_changes_of_the_release_notes(self):
        notes = Path(tempfile.mkdtemp(), "RELEASE_NOTES_v0.1.1.md")
        notes.write_text("# VietDoc OCR v0.1.1\n\nIntro.\n\n## Thay đổi mới\n\n- Chỉ còn Bóc tách nhanh.\n\n## Yêu cầu\n\nWindows.\n",
                         encoding="utf-8")
        changes = publish.whats_new(notes)
        self.assertEqual(changes, "- Chỉ còn Bóc tách nhanh.")
        self.assertEqual(publish.whats_new(notes.with_name("missing.md")), "")
        page = publish.body("0.1.1", HEAD, "lahieuphong/OCR", changes)
        self.assertTrue(page.startswith("## Có gì mới\n\n- Chỉ còn Bóc tách nhanh.\n\n## Tải về"))
        self.assertNotIn("Windows.", page)
        self.assertIn("Bóc tách nhanh", publish.whats_new(REPO_NOTES))   # the real notes of this release parse


class EmbeddedArchiveTest(unittest.TestCase):
    def test_finds_and_carves_the_stored_app_archive(self):
        body = b"x" * 50
        header = build_release.SEVEN_Z_SIGNATURE + b"\x00\x04" + b"\0" * 4 + struct.pack("<QQ", len(body), 10) + b"\0" * 4
        archive = header + body + b"y" * 10
        setup = Path(tempfile.mkdtemp(), "setup.exe")
        setup.write_bytes(b"MZ stub" + archive + b"trailer")
        self.assertEqual(build_release.find_embedded_7z(setup), (7, len(archive)))
        target = setup.with_name("app-64.7z")
        build_release.carve_embedded_7z(setup, target)
        self.assertEqual(target.read_bytes(), archive)

    def test_no_archive_stops_the_build(self):
        setup = Path(tempfile.mkdtemp(), "setup.exe")
        setup.write_bytes(b"MZ nothing here")
        with self.assertRaises(build_release.BuildError):
            build_release.find_embedded_7z(setup)


class UpdateFeedTest(unittest.TestCase):
    def test_reads_the_feed_of_app_update_yml(self):
        path = Path(tempfile.mkdtemp(), "app-update.yml")
        path.write_text("owner: lahieuphong\nrepo: OCR\nprovider: github\nreleaseType: release\nupdaterCacheDirName: x\n",
                        encoding="utf-8")
        self.assertEqual(build_release.update_feed(path), build_release.EXPECTED_FEED)
        self.assertEqual(build_release.update_feed(path.with_name("missing.yml")), {})

    def test_writes_the_feed_electron_builder_would_write(self):
        resources = Path(tempfile.mkdtemp())
        path = build_release.write_update_feed(resources, "vietdoc-ocr-desktop")
        self.assertEqual(path.read_text(encoding="utf-8"),
                         "owner: lahieuphong\nrepo: OCR\nprovider: github\nreleaseType: release\n"
                         "updaterCacheDirName: vietdoc-ocr-desktop-updater\n")
        self.assertEqual(build_release.update_feed(path), build_release.EXPECTED_FEED)


if __name__ == "__main__":
    unittest.main()

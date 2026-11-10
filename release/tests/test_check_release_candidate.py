"""Synthetic unit tests; never load models, documents or release artifacts."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from release.check_release_candidate import REQUIRED, SCHEMA, verify


def digest(b):
    return hashlib.sha256(b).hexdigest()


class PublicReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.repo = self.dir / "checkout"
        self.repo.mkdir()
        self.evidence = self.dir / "private_evidence"
        self.evidence.mkdir()
        self.installer = self.dir / "VietDoc-OCR-v0.1.0-rc.1-Windows-x64-Setup.exe"
        self.installer.write_bytes(b"synthetic installer fixture only")
        self.portable = self.dir / "VietDoc-OCR-v0.1.0-rc.1-Windows-x64-Portable.zip"
        self.portable.write_bytes(b"synthetic portable fixture only")
        self.attestation = self.evidence / "attestation.json"
        self.commit = "a" * 40
        self.data = {
            "schema": SCHEMA, "tag": "v0.1.0-rc.1",
            "source_commit": self.commit, "installer_sha256": digest(self.installer.read_bytes()),
            "portable_sha256": digest(self.portable.read_bytes()),
            "gates": {},
        }
        for group, names in REQUIRED.items():
            self.data["gates"][group] = {}
            for name in names:
                path = self.evidence / f"{group}_{name}.txt"
                path.write_text(f"synthetic test evidence for {group}.{name}")
                self.data["gates"][group][name] = {
                    "status": "PASS", "report": str(path), "sha256": digest(path.read_bytes()),
                }

    def check(self):
        return verify(self.data, self.installer, self.repo, self.commit, self.attestation, self.portable)

    def test_synthetic_valid_attestation(self):
        self.assertEqual(self.check(), [])

    def test_missing_required_gates_fail(self):
        for group, names in REQUIRED.items():
            for name in names:
                old = self.data["gates"][group].pop(name)
                self.assertTrue(any(f"{group}.{name}: not PASS" in x for x in self.check()))
                self.data["gates"][group][name] = old

    def test_license_blocked(self):
        self.data["gates"]["legal"]["pymupdf_rights"]["status"] = "BLOCKED"
        self.assertIn("legal.pymupdf_rights: not PASS", self.check())

    def test_modified_installer_fails(self):
        self.installer.write_bytes(b"tampered")
        self.assertIn("installer SHA-256 mismatch", self.check())

    def test_modified_report_fails(self):
        path = Path(self.data["gates"]["qa"]["windows10_clean"]["report"])
        path.write_bytes(b"tampered")
        self.assertIn("qa.windows10_clean: report SHA-256 mismatch", self.check())

    def test_missing_report_fails(self):
        path = Path(self.data["gates"]["qa"]["windows10_clean"]["report"])
        path.unlink()
        self.assertIn("qa.windows10_clean: report missing or empty", self.check())

    def test_unrelated_tag_rejected(self):
        self.data["tag"] = "v99.0.0"
        self.assertTrue(any("tag must" in x for x in self.check()))

    def test_source_commit_mismatch_rejected(self):
        self.data["source_commit"] = "f" * 40
        self.assertIn("source_commit does not match expected commit", self.check())

    def test_inside_repo_proof_rejected(self):
        path = self.repo / "report.txt"
        path.write_bytes(b"synthetic")
        self.data["gates"]["legal"]["project_license_and_source"].update(report=str(path), sha256=digest(path.read_bytes()))
        self.assertTrue(any("external absolute report" in x for x in self.check()))

    def test_inside_repo_installer_rejected(self):
        inside = self.repo / self.installer.name
        inside.write_bytes(self.installer.read_bytes())
        errors = verify(self.data, inside, self.repo, self.commit, self.attestation)
        self.assertIn("installer must be outside Git checkout", errors)

    def test_wrong_attestation_location_rejected(self):
        errors = verify(self.data, self.installer, self.repo, self.commit, self.repo / "local.json")
        self.assertIn("attestation must be outside Git checkout", errors)


class ReleaseFileTests(PublicReleaseGateTests):
    def test_portable_is_required_and_hashed(self):
        self.assertIn("portable missing", verify(self.data, self.installer, self.repo, self.commit, self.attestation))
        self.portable.write_bytes(b"tampered")
        self.assertIn("portable SHA-256 mismatch", self.check())

    def test_names_follow_the_tag(self):
        self.data["tag"] = "v0.1.0"
        errors = self.check()
        self.assertIn("incorrect installer filename", errors)
        self.assertIn("incorrect portable filename", errors)

    def test_internal_names_are_refused(self):
        internal = self.dir / "VietDoc-OCR-v0.1.0-INTERNAL-Windows-x64-Setup.exe"
        internal.write_bytes(self.installer.read_bytes())
        self.assertIn("incorrect installer filename",
                      verify(self.data, internal, self.repo, self.commit, self.attestation, self.portable))


if __name__ == "__main__":
    unittest.main()

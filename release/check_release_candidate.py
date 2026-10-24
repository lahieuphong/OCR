"""Offline integrity and evidence-completeness gate for VietDoc community releases.

NEVER publishes files. Validates hashes and required external QA reports only.
It CANNOT certify legal permissions or independently run Windows VM test cases.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SCHEMA = "vietdoc-community-release-attestation-v1"
HEX64 = re.compile(r"^[a-f0-9]{64}$")
HEX40 = re.compile(r"^[a-f0-9]{40}$")
TAG = re.compile(r"^v0\.1\.0(?:-rc\.[1-9][0-9]*)?$")
REQUIRED = {
    "legal": ("project_license_and_source", "pymupdf_rights", "vietocr_weights_rights",
              "paddle_detector_rights", "third_party_sbom_notices", "windows_runtime_rights"),
    "qa": ("windows11_clean", "windows10_clean", "network_blocked_ocr", "no_python_node_cache",
           "scanned_pdf", "text_layer_pdf", "png", "jpeg", "copy_export",
           "install_relaunch_uninstall", "model_tamper_fail_closed", "b1024_regression"),
    "security": ("history_privacy_audit", "installer_payload_scan", "authenticode_signed",
                 "release_smoke_disabled"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def external(path: Path, repo: Path) -> bool:
    return path.is_absolute() and not path.resolve().is_relative_to(repo.resolve())


def verify(data: dict, installer: Path, repo: Path, expected_commit: str,
           attestation: Path) -> list[str]:
    errors = []
    if data.get("schema") != SCHEMA:
        errors.append("attestation schema mismatch")
    if not HEX40.fullmatch(expected_commit):
        errors.append("expected commit is not a 40-character lowercase Git SHA")
    if data.get("source_commit") != expected_commit:
        errors.append("source_commit does not match expected commit")
    tag = data.get("tag")
    if not isinstance(tag, str) or not TAG.fullmatch(tag):
        errors.append("tag must be v0.1.0 or v0.1.0-rc.N")
    if not external(attestation, repo):
        errors.append("attestation must be outside Git checkout")
    if not external(installer, repo):
        errors.append("installer must be outside Git checkout")
    if installer.name != "VietDoc OCR Setup.exe":
        errors.append("incorrect installer filename")
    expected_hash = data.get("installer_sha256")
    if not isinstance(expected_hash, str) or not HEX64.fullmatch(expected_hash):
        errors.append("invalid installer_sha256")
    if not installer.is_file() or installer.stat().st_size == 0:
        errors.append("installer missing or empty")
    elif isinstance(expected_hash, str) and HEX64.fullmatch(expected_hash):
        if sha256(installer) != expected_hash:
            errors.append("installer SHA-256 mismatch")

    gates = data.get("gates")
    if not isinstance(gates, dict):
        return errors + ["gates must be an object"]
    for group, names in REQUIRED.items():
        section = gates.get(group)
        if not isinstance(section, dict):
            errors.append(f"missing gate group: {group}")
            continue
        for name in names:
            key = f"{group}.{name}"
            entry = section.get(name)
            if not isinstance(entry, dict) or entry.get("status") != "PASS":
                errors.append(f"{key}: not PASS")
                continue
            report = entry.get("report")
            checksum = entry.get("sha256")
            if not isinstance(report, str) or not external(Path(report), repo):
                errors.append(f"{key}: external absolute report path required")
                continue
            if not isinstance(checksum, str) or not HEX64.fullmatch(checksum):
                errors.append(f"{key}: invalid proof SHA-256")
                continue
            path = Path(report)
            if not path.is_file() or path.stat().st_size == 0:
                errors.append(f"{key}: report missing or empty")
            elif sha256(path) != checksum:
                errors.append(f"{key}: report SHA-256 mismatch")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--attestation", type=Path, required=True)
    ap.add_argument("--installer", type=Path, required=True)
    ap.add_argument("--source-sha", required=True)
    ap.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = ap.parse_args()
    try:
        data = json.loads(args.attestation.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("attestation must be an object")
        errors = verify(data, args.installer, args.repo_root, args.source_sha, args.attestation)
    except (ValueError, OSError) as exc:
        print(f"NO-GO: cannot read evidence: {type(exc).__name__}: {exc}")
        return 2
    if errors:
        print("NO-GO")
        for message in errors:
            print(f"- {message}")
        return 1
    print(f"EVIDENCE COMPLETE: installer hash and {sum(map(len, REQUIRED.values()))} external report hashes verified")
    print("REQUIRES OWNER REVIEW: hashes cannot establish license rights or independent VM test authenticity")
    return 0


if __name__ == "__main__":
    sys.exit(main())

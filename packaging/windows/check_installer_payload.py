"""Require the NSIS app archive to be byte-identical to the already checked folder app.

The workflow extracts NSIS and its app-64.7z outside the checkout before calling
this tool. No installer is executed, installed or granted elevation by this check.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def manifest(root: Path) -> dict[str, str]:
    root = root.resolve(strict=True)
    found = {}
    for file in sorted(root.rglob("*")):
        if file.is_symlink():
            raise ValueError("Unexpected symbolic link in Windows app")
        if not file.is_file():
            continue
        h = hashlib.sha256()
        with file.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1 << 20), b""):
                h.update(chunk)
        found[file.relative_to(root).as_posix()] = h.hexdigest()
    return found


def verify(checked: Path, extracted: Path, exe_name: str) -> dict:
    baseline = manifest(checked)
    payload = manifest(extracted)
    required = {exe_name, "resources/app.asar", "resources/backend/vietdoc-backend/vietdoc-backend.exe"}
    missing_required = sorted(required - baseline.keys())
    changed = sorted(name for name in baseline.keys() & payload.keys() if baseline[name] != payload[name])
    missing = sorted(baseline.keys() - payload.keys())
    extra = sorted(payload.keys() - baseline.keys())
    return {"result": "PASS" if not (missing_required or changed or missing or extra) else "FAIL",
            "checked_files": len(baseline), "payload_files": len(payload),
            "missing_required": missing_required, "changed": changed, "missing": missing, "extra": extra}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("checked", type=Path)
    parser.add_argument("extracted", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--exe-name", default="VietDoc OCR Test.exe")
    args = parser.parse_args()
    report = verify(args.checked, args.extracted, args.exe_name)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Scan a packaged VietDoc OCR folder for private material and write its build manifest.

Fails (exit 1) when the build carries anything it must never carry:
  - model weights, documents, archives of data, OCR exports, local config, logs or key files,
  - secret-looking content (private keys, tokens; the rules of .github/scripts/check_tracked_files.py),
  - machine paths given with --forbid-string (the checkout, the build user's profile folder),
  - a model_lock.json that is not hashes-only.
Always writes <out>/manifest.tsv (relative path, size, SHA-256 of every file) and <out>/scan.json.
Reads files only; never modifies the build.

Usage: python packaging/ci/scan_bundle.py <app dir> <out dir> [--forbid-string TEXT ...]
The optional --allow-internal-symlinks accepts macOS framework links only when
their resolved target exists inside the scanned app; escaping/broken links fail.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

FORBIDDEN_FILES = [
    ("model weights or checkpoint", re.compile(r"\.(onnx|pth|pt|ckpt|safetensors|pdparams|pdiparams|pdmodel|pdopt|h5|tflite)$", re.I)),
    ("document", re.compile(r"\.(pdf|docx?|xlsx?|pptx?|odt|rtf)$", re.I)),
    ("data archive or dump", re.compile(r"\.(tgz|tar|7z|rar|jsonl|sqlite3?|db)$", re.I)),
    ("OCR export", re.compile(r"_(vietocr_ocr|native_text)[^/]*\.(json|txt)$")),
    ("private key or keystore", re.compile(r"\.(key|pfx|p12|jks|keystore)$", re.I)),
    ("environment file", re.compile(r"(^|/)\.env($|\.)")),
    ("local desktop config", re.compile(r"(^|/)desktop\.config\.json$")),
    ("log or smoke report", re.compile(r"(\.log$|(^|/)smoke_report\.json$)")),
    ("pip build-path record", re.compile(r"(^|/)direct_url\.json$")),
]
# Public material that matches a rule above by name only.
ALLOWED_FILES = [
    re.compile(r"/certifi/cacert\.pem$"),  # Mozilla's public CA bundle (not a private key)
]
SECRET_CONTENT = [
    ("private key block", re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("GitHub token", re.compile(rb"(ghp|gho|ghs|ghu)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}")),
    ("GitLab token", re.compile(rb"glpat-[A-Za-z0-9_-]{20,}")),
    # A standalone key only: Electron's own executable carries the same 20 characters inside a long base64
    # blob (identical offset in node_modules/electron/dist/electron.exe), which is not a credential.
    ("AWS access key", re.compile(rb"(?<![A-Za-z0-9+/])AKIA[0-9A-Z]{16}(?![A-Za-z0-9+/=])")),
    ("Slack token", re.compile(rb"xox[abp]-[A-Za-z0-9-]{10,}")),
    ("API secret key", re.compile(rb"sk-[A-Za-z0-9]{32,}")),
]
PEM_ALLOWED = re.compile(r"\.pem$", re.I)  # .pem is checked by content (private key block), not by name


# Only these six compiled wheel extensions were found to contain GitHub runner profile
# paths in PE debug data. Even here, permit ONLY the explicitly supplied profile when
# the bundled extension SHA-256 equals its original, unmodified installed wheel.
# All other sensitive strings, other paths and modified binaries remain forbidden.
VERIFIED_NATIVE_WHEELS = frozenset({
    "bidi/bidi.cp312-win_amd64.pyd",
    "cryptography/hazmat/bindings/_rust.pyd",
    "pydantic_core/_pydantic_core.cp312-win_amd64.pyd",
    "safetensors/_safetensors_rust.pyd",
    "shapely/_geometry_helpers.cp312-win_amd64.pyd",
    "shapely/_geos.cp312-win_amd64.pyd",
})
PACKAGED_NATIVE_PREFIX = "resources/backend/vietdoc-backend/_internal/"


def encoded_variants(text: str) -> set[bytes]:
    variants = {text, text.replace(chr(92), "/"), text.replace("/", chr(92)), text.lower()}
    return {data for value in variants for data in (value.encode("utf-8"), value.encode("utf-16-le"))}


def verified_upstream_native(rel: str, digest: str, wheel_root: str | None) -> bool:
    if not wheel_root or not rel.startswith(PACKAGED_NATIVE_PREFIX):
        return False
    suffix = rel[len(PACKAGED_NATIVE_PREFIX):]
    if suffix not in VERIFIED_NATIVE_WHEELS:
        return False
    original = Path(wheel_root).joinpath(*suffix.split("/"))
    return original.is_file() and not original.is_symlink() and sha256(str(original)) == digest


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan(root: str, forbid: list[str], *, wheel_root: str | None = None,
         wheel_profile: str | None = None, allow_internal_symlinks: bool = False) -> tuple[list[dict], list[tuple[str, int, str]], list[dict]]:
    findings, manifest = [], []
    needles = set().union(*(encoded_variants(value) for value in forbid if value))
    profile_needles = (encoded_variants(wheel_profile) & needles) if wheel_root and wheel_profile in forbid else set()
    verified_paths = set()
    resolved_root = Path(root).resolve(strict=True)

    def link_problem(full: str) -> str | None:
        candidate = Path(full)
        if not candidate.is_symlink() and not (hasattr(candidate, "is_junction") and candidate.is_junction()):
            return None
        if not allow_internal_symlinks:
            return "symbolic link or junction"
        try:
            target = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            return "broken or cyclic symbolic link"
        if not target.is_relative_to(resolved_root):
            return "symbolic link escapes the app"
        return None

    # Directory aliases are never traversed: their real targets are scanned once.
    # File aliases are scanned under their own name as well, so .onnx -> innocent.bin fails.
    for dirpath, dirnames, filenames in os.walk(root):
        for d in list(dirnames):
            full = os.path.join(dirpath, d)
            candidate = Path(full)
            if candidate.is_symlink() or (hasattr(candidate, "is_junction") and candidate.is_junction()):
                problem = link_problem(full)
                if problem:
                    findings.append({"path": os.path.relpath(full, root).replace(os.sep, "/"), "reason": problem})
                dirnames.remove(d)
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            problem = link_problem(full)
            if problem:
                findings.append({"path": rel, "reason": problem})
                continue
            size = os.path.getsize(full)
            digest = sha256(full)
            manifest.append((rel, size, digest))
            if not any(rx.search("/" + rel) for rx in ALLOWED_FILES):
                findings += [{"path": rel, "reason": reason} for reason, rx in FORBIDDEN_FILES if rx.search(rel)]
            with open(full, "rb") as f:
                data = f.read()
            findings += [{"path": rel, "reason": reason} for reason, rx in SECRET_CONTENT if rx.search(data)]
            native_matches_wheel = bool(profile_needles) and verified_upstream_native(rel, digest, wheel_root)
            for n in needles:
                if n not in data:
                    continue
                if native_matches_wheel and n in profile_needles:
                    verified_paths.add(rel)
                    continue
                findings.append({"path": rel, "reason": "machine path " + n.decode("utf-8", "replace").replace(chr(0), "")})
            if name == "model_lock.json":
                lock = json.loads(data)
                text = json.dumps(lock)
                if re.search(r"[A-Za-z]:[\\/]|/home/|/Users/", text):
                    findings.append({"path": rel, "reason": "model_lock.json contains a path"})
    warnings = [{"path": rel, "reason": "byte-identical upstream wheel has CI profile debug data"}
                for rel in sorted(verified_paths)]
    return findings, sorted(manifest), warnings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root")
    ap.add_argument("out")
    ap.add_argument("--forbid-string", action="append", default=[])
    ap.add_argument("--allow-internal-symlinks", action="store_true",
                    help="accept existing links resolving inside the app (macOS frameworks); never follow directory aliases")
    ap.add_argument("--verified-wheel-root", help="site-packages directory of the installed wheels")
    ap.add_argument("--verified-wheel-profile", help="CI account profile already in --forbid-string")
    a = ap.parse_args()
    if bool(a.verified_wheel_root) != bool(a.verified_wheel_profile):
        ap.error("both verified wheel arguments must be provided")
    os.makedirs(a.out, exist_ok=True)
    findings, manifest, warnings = scan(a.root, a.forbid_string,
                                        wheel_root=a.verified_wheel_root, wheel_profile=a.verified_wheel_profile,
                                        allow_internal_symlinks=a.allow_internal_symlinks)
    with open(os.path.join(a.out, "manifest.tsv"), "w", encoding="utf-8", newline="\n") as f:
        f.write("path\tsize\tsha256\n")
        f.writelines(f"{p}\t{s}\t{h}\n" for p, s, h in manifest)
    summary = {"root": os.path.basename(os.path.abspath(a.root)), "files": len(manifest),
               "bytes": sum(s for _, s, _ in manifest), "forbid_strings": len(a.forbid_string),
               "findings": findings, "verified_wheel_warnings": warnings, "result": "FAIL" if findings else "PASS"}
    with open(os.path.join(a.out, "scan.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print(f"{summary['result']}: {summary['files']} files, {summary['bytes']} bytes, {len(findings)} finding(s)")
    for item in findings[:50]:
        print(f"  {item['reason']}: {item['path']}")
    for item in warnings:
        print(f"  NOTE: {item['reason']}: {item['path']}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

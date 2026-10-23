"""Scan a packaged VietDoc OCR folder for private material and write its build manifest.

Fails (exit 1) when the build carries anything it must never carry:
  - model weights, documents, archives of data, OCR exports, local config, logs or key files,
  - secret-looking content (private keys, tokens; the rules of .github/scripts/check_tracked_files.py),
  - machine paths given with --forbid-string (the checkout, the build user's profile folder),
  - a model_lock.json that is not hashes-only.
Always writes <out>/manifest.tsv (relative path, size, SHA-256 of every file) and <out>/scan.json.
Reads files only; never modifies the build.

Usage: python packaging/ci/scan_bundle.py <win-unpacked dir> <out dir> [--forbid-string TEXT ...]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

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


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan(root: str, forbid: list[str]) -> tuple[list[dict], list[tuple[str, int, str]]]:
    findings, manifest = [], []
    needles = []
    for text in forbid:
        if text:
            for variant in {text, text.replace("\\", "/"), text.replace("/", "\\"), text.lower()}:
                needles += [variant.encode("utf-8"), variant.encode("utf-16-le")]
    for dirpath, dirnames, filenames in os.walk(root):
        for d in list(dirnames):
            if os.path.islink(os.path.join(dirpath, d)):
                findings.append({"path": os.path.relpath(os.path.join(dirpath, d), root), "reason": "symbolic link or junction"})
                dirnames.remove(d)
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            size = os.path.getsize(full)
            manifest.append((rel, size, sha256(full)))
            if not any(rx.search("/" + rel) for rx in ALLOWED_FILES):
                findings += [{"path": rel, "reason": reason} for reason, rx in FORBIDDEN_FILES if rx.search(rel)]
            with open(full, "rb") as f:
                data = f.read()
            findings += [{"path": rel, "reason": reason} for reason, rx in SECRET_CONTENT if rx.search(data)]
            findings += [{"path": rel, "reason": "machine path " + n.decode("utf-8", "replace").replace("\0", "")}
                         for n in dict.fromkeys(needles) if n in data]
            if name == "model_lock.json":
                lock = json.loads(data)
                text = json.dumps(lock)
                if re.search(r"[A-Za-z]:[\\/]|/home/|/Users/", text):
                    findings.append({"path": rel, "reason": "model_lock.json contains a path"})
    return findings, sorted(manifest)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root")
    ap.add_argument("out")
    ap.add_argument("--forbid-string", action="append", default=[])
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    findings, manifest = scan(a.root, a.forbid_string)
    with open(os.path.join(a.out, "manifest.tsv"), "w", encoding="utf-8", newline="\n") as f:
        f.write("path\tsize\tsha256\n")
        f.writelines(f"{p}\t{s}\t{h}\n" for p, s, h in manifest)
    summary = {"root": os.path.basename(os.path.abspath(a.root)), "files": len(manifest),
               "bytes": sum(s for _, s, _ in manifest), "forbid_strings": len(a.forbid_string),
               "findings": findings, "result": "FAIL" if findings else "PASS"}
    with open(os.path.join(a.out, "scan.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print(f"{summary['result']}: {summary['files']} files, {summary['bytes']} bytes, {len(findings)} finding(s)")
    for item in findings[:50]:
        print(f"  {item['reason']}: {item['path']}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

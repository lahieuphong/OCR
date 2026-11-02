"""Fail if Git tracks material that must stay local (model-free CI gate).

Checks every file tracked at HEAD and, with --history-base REF, every file that the
commits REF..HEAD add or change: a blob stays in history even if it is deleted later.

PaddleOCR/ is the vendored upstream snapshot that main already holds (its own docs
images and docker .env templates). Inside it only the model, key-file and
secret-content rules apply; everything else is checked everywhere.

Usage: python .github/scripts/check_tracked_files.py [--history-base origin/main]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

VENDORED = "PaddleOCR/"
MAX_BYTES = 5 * 1024 * 1024

EVERYWHERE = [
    ("model weights or checkpoint", re.compile(r"\.(onnx|pth|pt|ckpt|safetensors|pdparams|pdiparams|pdmodel|pdopt|h5|tflite)$", re.I)),
    ("private key or certificate", re.compile(r"\.(pem|key|pfx|p12)$", re.I)),
]
OUTSIDE_VENDORED = [
    ("local model folder", re.compile(r"^models/")),
    ("quality-lab output", re.compile(r"(^|/)quality_(work|outputs)/")),
    ("real-document crops", re.compile(r"(^|/)real_work/")),
    ("source documents folder", re.compile(r"^sources/")),
    ("review pack", re.compile(r"^vietdoc_[^/]*/")),
    ("virtual environment", re.compile(r"(^|/)\.venv[^/]*/")),
    ("node_modules", re.compile(r"(^|/)node_modules/")),
    ("frontend build output", re.compile(r"(^|/)frontend/dist/")),
    ("blind set or blind input", re.compile(r"blind_(test|inputs?)", re.I)),
    ("prediction dump", re.compile(r"(^|/)(predictions_[^/]*\.jsonl|eval_inputs\.jsonl)$")),
    ("human label export", re.compile(r"(verified_labels|blind_review_export|correction_addendum|label_quarantine)", re.I)),
    ("training or real-line manifest", re.compile(r"(^|/)(real|synthetic)_(train|val)\.tsv$|(^|/)manifests/[^/]*\.tsv$")),
    ("app OCR export", re.compile(r"_(vietocr_ocr|native_text|hybrid_h1|metadata_fast)[^/]*\.(json|txt)$")),
    ("document or image", re.compile(r"\.(pdf|png|jpe?g|tiff?|bmp|webp|heic)$", re.I)),
    ("archive", re.compile(r"\.(zip|tgz|tar|gz|7z|rar)$", re.I)),
    ("environment file", re.compile(r"(^|/)\.env($|\.(?!example$))")),
]
SECRET_CONTENT = [
    ("private key block", re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("GitHub token", re.compile(rb"(ghp|gho|ghs|ghu)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}")),
    ("GitLab token", re.compile(rb"glpat-[A-Za-z0-9_-]{20,}")),
    ("AWS access key", re.compile(rb"AKIA[0-9A-Z]{16}")),
    ("Slack token", re.compile(rb"xox[abp]-[A-Za-z0-9-]{10,}")),
    ("API secret key", re.compile(rb"sk-[A-Za-z0-9]{32,}")),
]


def git(*args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(["git", "-c", "core.quotepath=off", *args], input=data, capture_output=True, check=True).stdout


def path_problems(path: str) -> list[str]:
    rules = EVERYWHERE + ([] if path.startswith(VENDORED) else OUTSIDE_VENDORED)
    return [reason for reason, rx in rules if rx.search(path)]


def blob_problems(path: str, size: int, data: bytes) -> list[str]:
    found = []
    if size > MAX_BYTES and not path.startswith(VENDORED):
        found.append(f"larger than {MAX_BYTES // (1024 * 1024)} MB ({size} bytes)")
    if b"\0" not in data[:8000]:
        found += [reason for reason, rx in SECRET_CONTENT if rx.search(data)]
    return found


def blobs(entries: list[tuple[str, str]]) -> list[tuple[str, str, int, bytes]]:
    """(path, oid) -> (path, oid, size, content) via one cat-file batch."""
    if not entries:
        return []
    out = git("cat-file", "--batch", data="".join(f"{oid}\n" for _, oid in entries).encode())
    result, pos = [], 0
    for path, oid in entries:
        header_end = out.index(b"\n", pos)
        _, kind, size = out[pos:header_end].decode().split()
        size = int(size)
        content = out[header_end + 1: header_end + 1 + size]
        pos = header_end + 1 + size + 1
        if kind == "blob":
            result.append((path, oid, size, content))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-base", help="also check every blob the commits BASE..HEAD add or change")
    args = parser.parse_args()

    tracked = []
    for line in git("ls-files", "-s", "-z").split(b"\0"):
        if line:
            meta, path = line.decode("utf-8").split("\t", 1)
            mode, oid, _stage = meta.split()
            if mode != "160000":  # submodule gitlinks have no blob
                tracked.append((path, oid))
    entries = {("HEAD", path, oid) for path, oid in tracked}
    if args.history_base:
        for line in git("rev-list", "--objects", f"{args.history_base}..HEAD").decode("utf-8").splitlines():
            oid, _, path = line.partition(" ")
            if path:
                entries.add((f"history {args.history_base}..HEAD", path, oid))

    problems = []
    for scope, path, oid in sorted(entries):
        for reason in path_problems(path):
            problems.append(f"[{scope}] {path}: {reason}")
    checked = blobs(sorted({(path, oid) for _, path, oid in entries}))
    for path, oid, size, data in checked:
        for reason in blob_problems(path, size, data):
            problems.append(f"[blob {oid[:12]}] {path}: {reason}")

    print(f"checked {len(tracked)} tracked files and {len(checked)} blobs"
          + (f" (history {args.history_base}..HEAD included)" if args.history_base else ""))
    if problems:
        print("SENSITIVE OR FORBIDDEN MATERIAL:\n  " + "\n  ".join(sorted(set(problems))))
        return 1
    print("no sensitive tracked material found")
    return 0


if __name__ == "__main__":
    sys.exit(main())

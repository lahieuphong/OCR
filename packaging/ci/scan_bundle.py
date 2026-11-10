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
The optional --allow-locked-models <model_lock.json> is for the offline release build, which carries the
verified models: exactly the locked files at their bundled paths with their locked SHA-256 are accepted,
and every one of them must be there. Any other weight file, a renamed copy or a changed byte still fails.
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
    ("OCR export", re.compile(r"_(vietocr_ocr|native_text|hybrid_h1|metadata_fast)[^/]*\.(json|txt)$")),
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


# OpenCV 4.10.0.84's public macOS arm64 wheel (SHA-256
# ee4b0919026d8c533aeb69b16c6ec4a891a2f6844efaa14121bf68838753209c)
# carries PEM parser constants in mbedTLS and public known-answer keys in GnuTLS.
# Every complete key was compared byte-for-byte against the public upstream self-tests:
# https://github.com/gnutls/gnutls/blob/3.8.5/lib/crypto-selftests-pk.c
# Only those exact C strings in the two expected ARM64 Mach-O libraries are accepted.
# Additional or modified keys in the SAME binary still fail; no binary/file is exempted.
MAC_CRYPTO_PREFIX = "Contents/Resources/backend/vietdoc-backend/_internal/"
PUBLIC_GNUTLS_SELF_TESTS = frozenset({
    "f4b1de2f94f1df2d588ff6c18290e0f7f5091267b9ef0da8433c622bad3d127a",  # rsa_2048_privkey
    "80ec06e06b06635bcad5c71b0e9e7a3516c02133c682a2369b09599addb8d7f3",  # dsa_2048_privkey
    "d653005e4d23cf91e3572fe8148ab6db2e474924d9711838521d3ba352b193f5",  # ecdsa_secp256r1_privkey
    "293216817f0d585f0b54f225582f59e7b2e2a795b5f8002e2d71c5e3d49ce9b0",  # ecdsa_secp384r1_privkey
    "f8766749b0c6f9b5661364568226af0ba7ae8d87c0073df24e440de4417521cd",  # ecdsa_secp521r1_privkey
    "934b3e9bfd9936c5e30c7f0ed7d36a05e2044f755c0aa433e1d6bef6a68d1391",  # ecdsa_secp192r1_privkey
    "a0b9679665e29ac220dfb0b366317e1b9dd5fe31e9def8b2e511669a041389ae",  # ecdsa_secp224r1_privkey
    "b8369cc647a1e1e8f8e420b6b8580c36223f89b0f8e70281732d028aebf15fac",  # gost01_privkey
    "3de5d1d9ca9af8e24d29bab925c3d500c2cdd11a06c4a2c6a6b336e73bb3ad56",  # gost12_256_privkey
    "c72070fc1ffb2df729650b949157c85ec03d8ec9743ba7956c03e21d385bce4e",  # gost12_512_privkey
})
MBEDTLS_PEM_HEADERS = frozenset(
    b"-----BEGIN " + label + b"PRIVATE KEY-----"
    for label in (b"", b"RSA ", b"EC ", b"ENCRYPTED ")
)


def public_crypto_match(rel: str, data: bytes, match: re.Match) -> bool:
    if not rel.startswith(MAC_CRYPTO_PREFIX) or data[:8] != bytes.fromhex("cffaedfe0c000001"):
        return False
    library = rel[len(MAC_CRYPTO_PREFIX):]
    if library in {"libmbedcrypto.3.5.1.dylib", "cv2/.dylibs/libmbedcrypto.3.5.1.dylib"}:
        # A parser's header literal contains no key body: it ends at its own NUL.
        # The newline+NUL form is also present in the exact upstream wheel.
        return (match.group() in MBEDTLS_PEM_HEADERS and match.start() > 0
                and data[match.start() - 1] == 0
                and (data[match.end():match.end() + 1] == b"\0"
                     or data[match.end():match.end() + 2] == b"\n\0"))
    if library in {"libgnutls.30.dylib", "cv2/.dylibs/libgnutls.30.dylib"}:
        end = data.find(b"\0", match.end(), match.end() + 8192)
        return end >= 0 and hashlib.sha256(data[match.start():end]).hexdigest() in PUBLIC_GNUTLS_SELF_TESTS
    return False


def secret_findings(rel: str, data: bytes) -> tuple[list[dict], int]:
    findings, public_matches = [], 0
    for reason, pattern in SECRET_CONTENT:
        dangerous = False
        for match in pattern.finditer(data):
            if reason == "private key block" and public_crypto_match(rel, data, match):
                public_matches += 1
            else:
                dangerous = True
        if dangerous:
            findings.append({"path": rel, "reason": reason})
    return findings, public_matches


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


def locked_models(lock_path: str, prefix: str = "resources/") -> dict[str, str]:
    """Bundled path -> SHA-256 of every model file the offline release carries (desktop/model_lock.json).

    The layout is the one desktop/electron/lib/config.js reads: resources/models (VietOCR, repository layout)
    and resources/paddlex (a PaddleX home with the detector)."""
    with open(lock_path, encoding="utf-8") as f:
        lock = json.load(f)
    recognizer, detector = lock["recognizer"], lock["detector"]
    vietocr = prefix + "models/vietocr/"
    files = {
        vietocr + "onnx/exp_b_width1024/encoder.onnx": recognizer["encoder_sha256"],
        vietocr + "onnx/exp_b_width1024/decoder_step.onnx": recognizer["decoder_sha256"],
        vietocr + "finetuned/exp_b_width1024/weights.pth": recognizer["checkpoint_sha256"],
    }
    for name, digest in detector["files"].items():
        files[f"{prefix}paddlex/official_models/{detector['model_name']}/{name}"] = digest
    if not all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in files.values()):
        raise ValueError("model_lock.json must hold one SHA-256 per model file")
    return files


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan(root: str, forbid: list[str], *, wheel_root: str | None = None,
         wheel_profile: str | None = None, allow_internal_symlinks: bool = False,
         allowed_models: dict[str, str] | None = None) -> tuple[list[dict], list[tuple[str, int, str]], list[dict]]:
    findings, manifest = [], []
    allowed_models = allowed_models or {}
    locked_digests = set(allowed_models.values())
    needles = set().union(*(encoded_variants(value) for value in forbid if value))
    profile_needles = (encoded_variants(wheel_profile) & needles) if wheel_root and wheel_profile in forbid else set()
    verified_paths = set()
    public_crypto_paths = {}
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
            locked = allowed_models.get(rel) == digest
            if digest in locked_digests and not locked:
                # A locked model under another name (weights.bin, encoder.dat): extensions alone would miss it.
                findings.append({"path": rel, "reason": "copy of a locked model"})
            if not any(rx.search("/" + rel) for rx in ALLOWED_FILES):
                findings += [{"path": rel, "reason": reason} for reason, rx in FORBIDDEN_FILES
                             if rx.search(rel) and not (locked and reason == "model weights or checkpoint")]
            with open(full, "rb") as f:
                data = f.read()
            secrets, public_matches = secret_findings(rel, data)
            findings += secrets
            if public_matches:
                public_crypto_paths[rel] = public_matches
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
    found = {rel: digest for rel, _, digest in manifest}
    findings += [{"path": rel, "reason": "locked model missing or different"}
                 for rel, digest in sorted(allowed_models.items()) if found.get(rel) != digest]
    warnings = [{"path": rel, "reason": "byte-identical upstream wheel has CI profile debug data"}
                for rel in sorted(verified_paths)]
    warnings += [{"path": rel, "reason": "public upstream crypto parser constants or known-answer self-tests",
                  "matches": count} for rel, count in sorted(public_crypto_paths.items())]
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
    ap.add_argument("--allow-locked-models", metavar="MODEL_LOCK",
                    help="offline release build: accept exactly the locked model files (and require all of them)")
    a = ap.parse_args()
    if bool(a.verified_wheel_root) != bool(a.verified_wheel_profile):
        ap.error("both verified wheel arguments must be provided")
    allowed_models = locked_models(a.allow_locked_models) if a.allow_locked_models else {}
    os.makedirs(a.out, exist_ok=True)
    findings, manifest, warnings = scan(a.root, a.forbid_string,
                                        wheel_root=a.verified_wheel_root, wheel_profile=a.verified_wheel_profile,
                                        allow_internal_symlinks=a.allow_internal_symlinks,
                                        allowed_models=allowed_models)
    with open(os.path.join(a.out, "manifest.tsv"), "w", encoding="utf-8", newline="\n") as f:
        f.write("path\tsize\tsha256\n")
        f.writelines(f"{p}\t{s}\t{h}\n" for p, s, h in manifest)
    summary = {"root": os.path.basename(os.path.abspath(a.root)), "files": len(manifest),
               "bytes": sum(s for _, s, _ in manifest), "forbid_strings": len(a.forbid_string),
               "findings": findings,
               "verified_wheel_warnings": [w for w in warnings if "byte-identical" in w["reason"]],
               "public_crypto_warnings": [w for w in warnings if w["reason"].startswith("public upstream")],
               "locked_models": sorted(allowed_models),
               "result": "FAIL" if findings else "PASS"}
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

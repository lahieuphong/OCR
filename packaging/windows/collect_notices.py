"""Collect the licence notices of what the Windows release ships into one folder (resources/licenses).

Usage:
  python packaging/windows/collect_notices.py --backend <backend-dist>/vietdoc-backend --repo <checkout>
         --out <dir> [--detector-card <PP-OCRv6_medium_det/README.md>] [--vietocr-license <vietocr/LICENSE>]

Writes:
  <out>/THIRD_PARTY_NOTICES.txt  one line per component (name, version, declared licence, licence files) and a
                                 "NEEDS REVIEW" list: copyleft (GPL, LGPL, AGPL, MPL, EPL, ...) or unknown licences,
                                 the Microsoft C/C++ runtime, the model weights and VietDoc's own code;
  <out>/notices.json             the same data for reports;
  <out>/python/<name>/...        the licence files of each bundled Python distribution (from its dist-info and
                                 its package folder), the CPython licence;
  <out>/npm/<name>/...           the licence files of the npm packages bundled into the frontend build;
  <out>/models/...               the detector's model card and the VietOCR library licence.
Electron's own LICENSE.electron.txt and LICENSES.chromium.html ship beside the executable and are referenced.

This is input for the owner's licence review (release/LICENSING_AUDIT.md), not a clearance. It reads the build
and the checkout only and never edits them.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from email.parser import Parser
from pathlib import Path

LICENCE_FILE = re.compile(r"^(licen[cs]e|copying|notice|copyright|authors|thirdpartynotices|third_party_notices|patents)"
                          r"([._-].*)?$", re.I)
COPYLEFT = re.compile(r"\b(A?GPL|LGPL|GNU|MPL|Mozilla Public|EPL|Eclipse Public|CDDL|EUPL|Affero)\b", re.I)
UNKNOWN = {"", "unknown", "none", "other", "other/proprietary license", "unlicensed"}
ELECTRON_NATIVE = (
    ("ffmpeg.dll", "FFmpeg (Chromium's media library)", "LGPL-2.1-or-later",
     "LGPL library: keep it a separate replaceable DLL and provide its notice and source offer"),
    ("d3dcompiler_47.dll", "Microsoft D3DCompiler", "Microsoft redistributable",
     "redistribution terms of the Microsoft DirectX shader compiler shipped with Electron"),
)
MSVC_RUNTIME = re.compile(r"^(vcruntime|msvcp|vcomp|concrt|vccorlib)\d*.*\.dll$", re.I)


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._@+-]", "_", name).strip("._") or "unnamed"


def declared_licence(meta) -> str:
    """License-Expression (PEP 639), else License, else the licence classifiers."""
    expression = (meta.get("License-Expression") or "").strip()
    if expression:
        return expression
    text = (meta.get("License") or "").strip()
    if text and "\n" not in text and len(text) <= 120:
        return text
    classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    if classifiers:
        return "; ".join(classifiers)
    return "full text in licence file" if text else ""


def review_reason(licence: str) -> str | None:
    if licence.strip().lower() in UNKNOWN:
        return "licence not declared"
    if COPYLEFT.search(licence):
        return "copyleft or source-sharing licence"
    return None


def copy_licence_files(files: list[Path], target: Path) -> list[str]:
    copied = []
    for source in files:
        destination = target / source.name
        index = 2
        while destination.exists():
            destination = target / f"{source.stem}.{index}{source.suffix}"
            index += 1
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        copied.append(destination.name)
    return copied


def python_components(internal: Path, out: Path) -> list[dict]:
    components = []
    for info in sorted(internal.glob("*.dist-info")):
        metadata = info / "METADATA"
        if not metadata.is_file():
            continue
        meta = Parser().parsestr(metadata.read_text(encoding="utf-8", errors="replace"))
        name, version = meta.get("Name") or info.name.split("-")[0], meta.get("Version") or ""
        files = [p for p in sorted(info.rglob("*")) if p.is_file() and (LICENCE_FILE.match(p.name)
                                                                         or p.relative_to(info).parts[0] == "licenses")]
        # Licence texts some packages keep in their package folder instead (onnxruntime, for example).
        tops = {name.lower().replace("-", "_")}
        if (info / "top_level.txt").is_file():
            tops |= {t.strip() for t in (info / "top_level.txt").read_text(encoding="utf-8", errors="replace").splitlines()
                     if t.strip() and "/" not in t and "\\" not in t}
        for top in sorted(tops):
            package = internal / top
            if package.is_dir():
                files += [p for p in sorted(package.iterdir()) if p.is_file() and LICENCE_FILE.match(p.name)]
        licence = declared_licence(meta)
        target = out / "python" / safe_name(name)
        components.append({"kind": "python", "name": name, "version": version, "licence": licence,
                           "files": [f"python/{safe_name(name)}/{f}" for f in copy_licence_files(files, target)],
                           "review": review_reason(licence)})
    return components


def npm_components(frontend: Path, out: Path) -> list[dict]:
    """Packages bundled into the production frontend build: the lockfile's non-development entries."""
    lock = json.loads((frontend / "package-lock.json").read_text(encoding="utf-8"))
    components, seen = [], set()
    # Top-level copies first, so a nested copy of the same version never replaces them.
    for key, entry in sorted(lock.get("packages", {}).items(), key=lambda item: (item[0].count("node_modules/"), item[0])):
        if not key.startswith("node_modules/") or entry.get("dev") or entry.get("devOptional"):
            continue
        name = key.rsplit("node_modules/", 1)[1]
        if (name, entry.get("version")) in seen:   # nested copies of the same version: listed once
            continue
        seen.add((name, entry.get("version")))
        folder = frontend / key
        files = [p for p in sorted(folder.iterdir()) if p.is_file() and LICENCE_FILE.match(p.name)] if folder.is_dir() else []
        licence = entry.get("license") or ""
        if not licence and (folder / "package.json").is_file():
            licence = json.loads((folder / "package.json").read_text(encoding="utf-8")).get("license") or ""
        licence = licence if isinstance(licence, str) else json.dumps(licence)
        target = out / "npm" / safe_name(name)
        components.append({"kind": "npm", "name": name, "version": entry.get("version", ""), "licence": licence,
                           "files": [f"npm/{safe_name(name)}/{f}" for f in copy_licence_files(files, target)],
                           "review": review_reason(licence) or (None if files else "no licence file in the package")})
    return components


def fixed_components(backend: Path, repo: Path, out: Path, detector_card: Path | None,
                     vietocr_licence: Path | None, electron_dist: Path | None = None) -> list[dict]:
    components = []
    cpython = Path(sys.base_prefix) / "LICENSE.txt"
    files = copy_licence_files([cpython], out / "python" / "CPython") if cpython.is_file() else []
    components.append({"kind": "runtime", "name": "CPython", "version": sys.version.split()[0],
                       "licence": "PSF-2.0", "files": [f"python/CPython/{f}" for f in files],
                       "review": None if files else "licence file not found"})
    runtime_dlls = sorted({p.name for p in backend.rglob("*.dll") if MSVC_RUNTIME.match(p.name)})
    if runtime_dlls:
        components.append({"kind": "runtime", "name": "Microsoft Visual C++ runtime", "version": "",
                           "licence": "Microsoft Software License Terms (redistributable code)", "files": [],
                           "detail": ", ".join(runtime_dlls),
                           "review": "redistribution terms of the Microsoft runtime DLLs shipped by the wheels"})
    package = json.loads((repo / "desktop" / "package.json").read_text(encoding="utf-8"))
    electron = package.get("devDependencies", {}).get("electron", "")
    components.append({"kind": "runtime", "name": "Electron (Chromium, Node.js)",
                       "version": electron, "licence": "MIT; Chromium notices",
                       "files": ["../../LICENSE.electron.txt", "../../LICENSES.chromium.html"], "review": None})
    # Native libraries beside VietDoc OCR.exe whose terms are not Electron's MIT licence.
    dist = electron_dist if electron_dist else repo / "desktop" / "node_modules" / "electron" / "dist"
    shipped = {p.name.lower() for p in dist.glob("*.dll")} if dist.is_dir() else set()
    for dll, name, licence, review in ELECTRON_NATIVE:
        if dll in shipped:
            components.append({"kind": "runtime", "name": name, "version": electron, "licence": licence,
                               "files": ["../../LICENSES.chromium.html"], "detail": dll, "review": review})
    bootloader = []
    try:
        import importlib.metadata as md
        bootloader = [Path(f.locate()) for f in md.distribution("pyinstaller").files or []
                      if LICENCE_FILE.match(Path(str(f)).name)]
    except Exception:   # PyInstaller is a build tool; without it here the entry still says what ships
        pass
    files = copy_licence_files([p for p in bootloader if p.is_file()], out / "python" / "PyInstaller-bootloader")
    components.append({"kind": "runtime", "name": "PyInstaller bootloader (vietdoc-backend.exe)", "version": "",
                       "licence": "GPL-2.0-or-later with the PyInstaller bootloader exception",
                       "files": [f"python/PyInstaller-bootloader/{f}" for f in files],
                       "review": None if files else "licence file not found"})
    components.append({"kind": "installer", "name": "NSIS installer and plug-ins (Setup only)", "version": "",
                       "licence": "zlib/libpng (NSIS); plug-ins such as nsis7z under LGPL-2.1",
                       "files": [], "review": "notices for the installer runtime electron-builder embeds in the Setup"})
    paddleocr = repo / "PaddleOCR" / "LICENSE"
    files = copy_licence_files([paddleocr], out / "models" / "PaddleOCR") if paddleocr.is_file() else []
    components.append({"kind": "source", "name": "PaddleOCR (vendored source)", "version": "", "licence": "Apache-2.0",
                       "files": [f"models/PaddleOCR/{f}" for f in files], "review": None if files else "licence file not found"})
    card = []
    if detector_card and detector_card.is_file():
        (out / "models" / "PP-OCRv6_medium_det").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(detector_card, out / "models" / "PP-OCRv6_medium_det" / "MODEL_CARD.md")
        card = ["models/PP-OCRv6_medium_det/MODEL_CARD.md"]
    declared = ""
    if card:
        match = re.search(r"^license:\s*(\S+)", (out / card[0]).read_text(encoding="utf-8", errors="replace"), re.M)
        declared = match.group(1) if match else ""
    components.append({"kind": "model", "name": "PP-OCRv6_medium_det (text detector weights)", "version": "",
                       "licence": declared or "not found", "files": card,
                       "review": "model weights: confirm the redistribution terms of this exact file"})
    files = copy_licence_files([vietocr_licence], out / "models" / "VietOCR") if vietocr_licence and vietocr_licence.is_file() else []
    components.append({"kind": "model", "name": "VietOCR B1024 (recognizer weights, fine-tuned from vgg_transformer)",
                       "version": "", "licence": "VietOCR library: Apache-2.0; weights: not established",
                       "files": [f"models/VietOCR/{f}" for f in files],
                       "review": "model weights: rights to the pretrained checkpoint, the training data and the fine-tuned files"})
    components.append({"kind": "app", "name": "VietDoc OCR (this application)", "version": package.get("version", ""),
                       "licence": "not chosen (no LICENSE file)", "files": [],
                       "review": "the owner must choose the application's licence (AGPL obligations if PyMuPDF is used under AGPL)"})
    return components


def write_report(components: list[dict], out: Path) -> dict:
    review = [c for c in components if c.get("review")]
    summary = {"components": len(components), "needs_review": len(review),
               "copyleft": sorted(c["name"] for c in components if c.get("review") == "copyleft or source-sharing licence"),
               "items": components}
    (out / "notices.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    lines = ["VietDoc OCR - third-party components and licences", "",
             "Generated from the build. Licence texts are in the folders named below.",
             "This list supports the licence review; it is not a licence grant or a legal clearance.", ""]
    for kind in ("app", "runtime", "installer", "model", "source", "python", "npm"):
        group = [c for c in components if c["kind"] == kind]
        if not group:
            continue
        lines.append(f"== {kind} ({len(group)})")
        for c in group:
            where = ", ".join(c["files"]) or "-"
            detail = f" [{c['detail']}]" if c.get("detail") else ""
            lines.append(f"{c['name']} {c['version']}".rstrip() + f" | {c['licence'] or 'not declared'}{detail} | {where}")
        lines.append("")
    lines.append(f"== NEEDS REVIEW ({len(review)})")
    lines += [f"{c['name']} {c['version']}".rstrip() + f": {c['review']}" for c in review]
    (out / "THIRD_PARTY_NOTICES.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return summary


def collect(backend: Path, repo: Path, out: Path, detector_card: Path | None = None,
            vietocr_licence: Path | None = None, electron_dist: Path | None = None) -> dict:
    internal = backend / "_internal"
    if not internal.is_dir():
        raise SystemExit(f"Not a PyInstaller one-folder backend: {backend}")
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"Output folder is not empty: {out}")
    out.mkdir(parents=True, exist_ok=True)
    components = fixed_components(backend, repo, out, detector_card, vietocr_licence, electron_dist)
    components += python_components(internal, out)
    components += npm_components(repo / "demo" / "local_pdf_ocr" / "frontend", out)
    return write_report(components, out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backend", type=Path, required=True, help="the PyInstaller folder (holds _internal)")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--detector-card", type=Path)
    parser.add_argument("--vietocr-license", type=Path)
    parser.add_argument("--electron-dist", type=Path, help="default: desktop/node_modules/electron/dist")
    args = parser.parse_args()
    summary = collect(args.backend, args.repo, args.out, args.detector_card, args.vietocr_license, args.electron_dist)
    print(json.dumps({k: summary[k] for k in ("components", "needs_review", "copyleft")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

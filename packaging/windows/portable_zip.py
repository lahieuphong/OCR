"""The Portable release of VietDoc OCR: one ZIP of the checked folder app, run without installing.

Layout (no wrapping folder, so Explorer's "Extract All" adds only the ZIP's own name to the path):
  VietDoc OCR/        the folder app, byte for byte (VietDoc OCR.exe, resources/ with backend, models, licences)
  VietDoc OCR Data/   empty: because it sits beside the app folder, settings, logs and browser data of this copy
                      stay here instead of %APPDATA% (desktop/electron/lib/app-identity.js, portableDataDir)
  <guide files>       given by the build (how to start, data folder, licence notice)

verify() reads every member back (decompressing it) and compares it with the folder's SHA-256 manifest, so the
ZIP holds exactly the checked app plus the named extras.
"""
from __future__ import annotations

import hashlib
import os
import zipfile
from pathlib import Path

APP_FOLDER = "VietDoc OCR"
DATA_FOLDER = "VietDoc OCR Data"


def file_manifest(root: Path) -> dict[str, str]:
    """Relative POSIX path -> SHA-256 of every file; links are refused (the app never holds any)."""
    found = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            full = Path(dirpath, name)
            if full.is_symlink() or (hasattr(full, "is_junction") and full.is_junction()):
                raise ValueError(f"Link in the app folder: {full}")
        for name in filenames:
            full = Path(dirpath, name)
            digest = hashlib.sha256()
            with full.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1 << 20), b""):
                    digest.update(chunk)
            found[full.relative_to(root).as_posix()] = digest.hexdigest()
    return found


def empty_dirs(root: Path) -> list[str]:
    return sorted(Path(d).relative_to(root).as_posix() for d, dirs, files in os.walk(root)
                  if not dirs and not files and Path(d) != root)


def make(app_dir: Path, zip_path: Path, extras: dict[str, Path]) -> None:
    """extras: name at the ZIP root -> source file (guides, notices)."""
    if zip_path.exists():
        raise FileExistsError(zip_path)
    for name in extras:
        if "/" in name or "\\" in name or name in (APP_FOLDER, DATA_FOLDER):
            raise ValueError(f"Extra file must be a plain name at the ZIP root: {name}")
    partial = zip_path.with_name(zip_path.name + ".partial")
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        archive.mkdir(DATA_FOLDER)
        for rel in empty_dirs(app_dir):
            archive.mkdir(f"{APP_FOLDER}/{rel}")
        for dirpath, _, filenames in os.walk(app_dir):
            for name in sorted(filenames):
                full = Path(dirpath, name)
                archive.write(full, f"{APP_FOLDER}/{full.relative_to(app_dir).as_posix()}")
        for name, source in extras.items():
            archive.write(source, name)
    partial.replace(zip_path)


def verify(zip_path: Path, app_dir: Path, extras: dict[str, Path], expected: dict[str, str] | None = None) -> dict:
    """expected: relative path -> SHA-256 of the app as it was scanned (default: the folder as it is now)."""
    current = file_manifest(app_dir)
    if expected is not None and expected != current:
        return {"result": "FAIL", "reason": "the app folder changed after it was scanned",
                "changed": sorted(n for n in expected.keys() | current.keys() if expected.get(n) != current.get(n))}
    expected = {f"{APP_FOLDER}/{rel}": digest for rel, digest in current.items()}
    for name, source in extras.items():
        expected[name] = hashlib.sha256(source.read_bytes()).hexdigest()
    expected_dirs = {f"{DATA_FOLDER}/"} | {f"{APP_FOLDER}/{rel}/" for rel in empty_dirs(app_dir)}
    found, dirs, unsafe = {}, set(), []
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            name = info.filename
            if name.startswith(("/", "\\")) or ".." in Path(name).parts or ":" in name or "\\" in name:
                unsafe.append(name)
                continue
            if info.is_dir():
                dirs.add(name)
                continue
            digest = hashlib.sha256()
            with archive.open(info) as stream:   # also checks the member's CRC-32
                for chunk in iter(lambda: stream.read(1 << 20), b""):
                    digest.update(chunk)
            found[name] = digest.hexdigest()
    changed = sorted(n for n in expected.keys() & found.keys() if expected[n] != found[n])
    missing = sorted(expected.keys() - found.keys())
    extra = sorted(found.keys() - expected.keys())
    missing_dirs = sorted(expected_dirs - dirs)
    ok = not (changed or missing or extra or missing_dirs or unsafe)
    return {"result": "PASS" if ok else "FAIL", "files": len(found), "app_files": len(expected) - len(extras),
            "changed": changed, "missing": missing, "extra": extra, "missing_dirs": missing_dirs, "unsafe_names": unsafe}

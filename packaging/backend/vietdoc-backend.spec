# -*- mode: python ; coding: utf-8 -*-
# Native PyInstaller one-folder build of the VietDoc desktop OCR server (internal).
# Environment and build command: packaging/README.md. Keep build and output folders OUTSIDE the repository.
#
# The bundle holds code and libraries only. No VietOCR model, PaddleOCR detector, document, label or
# token goes into it: the frozen models are read at run time from a verified external folder
# (VIETDOC_MODEL_ROOT) and checked by SHA-256 in demo/local_pdf_ocr/backend/contract.py.
import importlib.metadata as md
import os
import sys
from pathlib import Path, PurePath

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).resolve().parents[1]
SERVER = ROOT / "desktop" / "python" / "vietdoc_desktop_server.py"
RUNTIME_MODULES = Path(SPECPATH) / "runtime_modules.txt"

# Left out of the bundle: code the OCR server never runs. None of these was imported in any traced run
# (born-digital and scanned PDFs, PNG, JPG, both modes, with and without models), and each is reached only
# through a feature the app does not use.
EXCLUDED_MODULES = [
    "pip", "wheel",                                    # package installers
    "test", "_testcapi", "_testinternalcapi",          # CPython's own test suite
    "baidubce", "crc32c", "Crypto",                    # Baidu cloud SDK (aistudio_sdk upload, PaddleX serving)
    "future", "past", "libfuturize", "libpasteurize",  # Python 2 compatibility layer, used only by baidubce
    "hf_xet",                                          # Hugging Face transfer backend (downloads are disabled)
    "tkinter", "matplotlib", "IPython", "jupyter", "pytest", "torch", "tensorflow", "PyInstaller",
]
# Their metadata goes too, so nothing claims a package that is not there; build tools never ship.
EXCLUDED_DISTRIBUTIONS = {
    "pip", "wheel", "bce-python-sdk", "crc32c", "pycryptodome", "future", "hf-xet",
    "pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile", "pywin32-ctypes", "macholib",
}
# Libraries only loaded on demand (LoadLibrary) for features the OCR never uses, and files that only serve
# compiling against Paddle. No bundled binary imports any of these libraries.
UNUSED_PADDLE_LIBS = {
    "liblapack.dll", "libblas.dll", "libgfortran-3.dll", "libquadmath-0.dll", "libgcc_s_seh-1.dll",  # LAPACK
    "warpctc.dll", "warprnnt.dll",                                                                  # CTC/RNN-T loss (training)
}


def unused_file(dest: str) -> bool:
    path = PurePath(dest)
    parts = [part.lower() for part in path.parts]
    name, suffix = path.name.lower(), path.suffix.lower()
    return (name.startswith("opencv_videoio_ffmpeg")                      # OpenCV video I/O (FFmpeg)
            or (parts[:2] == ["onnxruntime", "capi"] and name == "onnxruntime.dll")  # C API; the Python binding links ORT statically
            or (parts[0] == "pil" and name.startswith("_avif"))           # optional AVIF codec; uploads are PDF/PNG/JPEG only
            or (parts[:2] == ["paddle", "libs"] and name in UNUSED_PADDLE_LIBS)
            or parts[:2] == ["paddle", "include"]                         # C++ headers for custom operators
            or (parts[0] == "paddle" and suffix in (".lib", ".pyi"))      # import libraries, type stubs
            or name == "direct_url.json")                                 # records a build-machine path


def excluded_metadata(dest: str) -> bool:
    """dist-info folders of excluded distributions (hooks may add some, e.g. pip's)."""
    top = PurePath(dest).parts[0].lower()
    return top.endswith(".dist-info") and top.split("-")[0] in {d.replace("-", "_") for d in EXCLUDED_DISTRIBUTIONS}


hiddenimports = [
    "demo.local_pdf_ocr.backend.app",
    "demo.local_pdf_ocr.backend.contract",
    "demo.local_pdf_ocr.backend.engine",
    "demo.local_pdf_ocr.backend.metadata_fast",
    "demo.local_pdf_ocr.backend.ocr_layout",
    "demo.local_pdf_ocr.backend.reading_order",
    "demo.local_pdf_ocr.backend.text_layer",
    "demo.local_pdf_ocr.backend.hybrid_h1",
    "demo.local_pdf_ocr.backend.hybrid_gates",
    "demo.local_pdf_ocr.backend.number_review_preview",
]
hiddenimports += collect_submodules("uvicorn")
# Paddle, PaddleX and PaddleOCR import modules by name: add every module a real run imported.
skip = ("__main__", "_distutils_hack", "distutils", "demo")
runtime = [m.strip() for m in RUNTIME_MODULES.read_text(encoding="utf-8").splitlines()
           if m.strip() and m.split(".")[0] not in skip]
clash = sorted(m for m in runtime if m.split(".")[0] in EXCLUDED_MODULES)
if clash:
    raise SystemExit(f"Excluded modules are used at run time: {clash[:10]}")
# The traced baseline comes from Windows. Darwin's standard-library imports are
# platform-specific and are not in that trace; avoid forcing Windows-only modules
# into a native macOS build. All OCR dependency and exclusion checks stay shared.
if sys.platform == "darwin":
    windows_only = {"_overlapped", "_winapi", "_wmi", "msvcrt", "nt", "winreg",
                    "asyncio.windows_events", "asyncio.windows_utils"}
    runtime = [module for module in runtime if module not in windows_only]
    hiddenimports += ["_scproxy", "_posixsubprocess", "resource", "fcntl", "pwd", "grp",
                      "termios", "asyncio.unix_events"]
hiddenimports += runtime

datas, binaries = [], []
for package in ("paddlex", "paddleocr", "paddle"):
    datas += collect_data_files(package, excludes=["**/tests/**", "**/*.pyc"])
binaries += collect_dynamic_libs("paddle")
if sys.platform == "darwin":
    # Paddle's prebuilt LAPACK libraries reference GCC runtimes that its wheel
    # omits. Collect the native build input explicitly; PyInstaller rewrites
    # their load commands to bundle-relative @rpath paths. Homebrew is never a
    # target-machine requirement. Do not discard optional inference libraries.
    gcc_dir_text = os.environ.get("VIETDOC_GCC_LIBDIR", "")
    gcc_dir = Path(gcc_dir_text)
    required_gcc = ("libgomp.1.dylib", "libgcc_s.1.1.dylib")
    if not gcc_dir_text or not gcc_dir.is_absolute() or not gcc_dir.is_dir():
        raise SystemExit("Set VIETDOC_GCC_LIBDIR to the native GCC library directory (packaging/macos/README.md)")
    if any(not (gcc_dir / name).is_file() for name in required_gcc):
        raise SystemExit(f"Native GCC runtime libraries missing from {gcc_dir}")
    gcc_libs = {gcc_dir / name for name in required_gcc}
    gcc_libs.update(gcc_dir.glob("libgcc*.dylib"))
    binaries += [(str(path), ".") for path in sorted(gcc_libs) if path.is_file()]
if sys.platform == "darwin":
    datas += [(str(ROOT / "packaging" / "macos" / "licenses" / name), "licenses/gcc")
              for name in ("COPYING3.txt", "COPYING.RUNTIME.txt")]
# License notices that live in the package folder instead of the dist-info folder.
datas += collect_data_files("onnxruntime", includes=["LICENSE", "ThirdPartyNotices.txt"])
# PaddleX checks its dependencies through importlib.metadata: ship the metadata of every bundled distribution.
for dist in md.distributions():
    name = dist.metadata["Name"]
    if name and name.lower() not in EXCLUDED_DISTRIBUTIONS:
        datas += copy_metadata(name)

a = Analysis(
    [str(SERVER)],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDED_MODULES,
    # LGPL-3.0 python-bidi stays as loose files, so it can be replaced in the installed app.
    module_collection_mode={"bidi": "py"},
    noarchive=False,
    optimize=0,
)
# Windows: Paddle Inference opens the detector files through narrow (ANSI) file APIs. When the system code page cannot
# spell the folder (a Vietnamese user name or folder name under code page 1252, for example), OCR stops with
# "(NotFound) Cannot open file ...\inference.json". activeCodePage UTF-8 (honoured from Windows 10 version 1903) makes
# those APIs take UTF-8 in this process only, so the bundled models load from any install or extract folder. The rest
# is PyInstaller's default manifest; Python itself already runs in UTF-8 mode (-X utf8 below).
WINDOWS_MANIFEST = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
    <application>
      <supportedOS Id="{e2011457-1546-43c5-a5fe-008deee3d3f0}"/>
      <supportedOS Id="{35138b9a-5d96-4fbd-8e2d-a2440225f93a}"/>
      <supportedOS Id="{4a2f28e3-53b9-4441-ba9c-d69d4a4a6e38}"/>
      <supportedOS Id="{1f676c76-80e1-4239-95bb-83d0f6d0da78}"/>
      <supportedOS Id="{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}"/>
    </application>
  </compatibility>
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <longPathAware xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">true</longPathAware>
      <activeCodePage xmlns="http://schemas.microsoft.com/SMI/2019/WindowsSettings">UTF-8</activeCodePage>
    </windowsSettings>
  </application>
</assembly>
"""
a.binaries = [entry for entry in a.binaries if not unused_file(entry[0])]
a.datas = [entry for entry in a.datas if not unused_file(entry[0]) and not excluded_metadata(entry[0])]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [("X utf8", None, "OPTION")],  # the development server also runs with -X utf8
    exclude_binaries=True,
    name="vietdoc-backend",
    console=True,  # Electron starts it hidden (windowsHide) and talks to it over pipes
    manifest=WINDOWS_MANIFEST if sys.platform == "win32" else None,
    upx=False,
    strip=False,
    debug=False,
    # A Windows backend cannot be cross-compiled into a Mac executable. Build on
    # Apple Silicon with native wheels; PyInstaller validates extension slices and
    # ad-hoc signs the rewritten Mach-O libraries and the backend executable.
    target_arch="arm64" if sys.platform == "darwin" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="vietdoc-backend")

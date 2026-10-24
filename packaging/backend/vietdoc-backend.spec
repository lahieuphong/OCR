# -*- mode: python ; coding: utf-8 -*-
# PyInstaller one-folder build of the VietDoc desktop OCR server (Windows Packaging Phase 1, internal).
# Environment and build command: packaging/README.md. Keep build and output folders OUTSIDE the repository.
#
# The bundle holds code and libraries only. No VietOCR model, PaddleOCR detector, document, label or
# token goes into it: the frozen models are read at run time from a verified external folder
# (VIETDOC_MODEL_ROOT) and checked by SHA-256 in demo/local_pdf_ocr/backend/contract.py.
import importlib.metadata as md
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
    "pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile", "pywin32-ctypes",
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
    "demo.local_pdf_ocr.backend.ocr_layout",
    "demo.local_pdf_ocr.backend.reading_order",
    "demo.local_pdf_ocr.backend.text_layer",
]
hiddenimports += collect_submodules("uvicorn")
# Paddle, PaddleX and PaddleOCR import modules by name: add every module a real run imported.
skip = ("__main__", "_distutils_hack", "distutils", "demo")
runtime = [m.strip() for m in RUNTIME_MODULES.read_text(encoding="utf-8").splitlines()
           if m.strip() and m.split(".")[0] not in skip]
clash = sorted(m for m in runtime if m.split(".")[0] in EXCLUDED_MODULES)
if clash:
    raise SystemExit(f"Excluded modules are used at run time: {clash[:10]}")
hiddenimports += runtime

datas, binaries = [], []
for package in ("paddlex", "paddleocr", "paddle"):
    datas += collect_data_files(package, excludes=["**/tests/**", "**/*.pyc"])
binaries += collect_dynamic_libs("paddle")
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
    upx=False,
    strip=False,
    debug=False,
)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="vietdoc-backend")

# VietDoc OCR — Windows packaging (Phase 1, internal prototype)

Builds a standalone Windows folder app (`win-unpacked`): Electron shell plus the OCR backend frozen with
PyInstaller, so the target machine needs neither Python nor Node.js. **Not for distribution**: the license
review is still open (PyMuPDF is AGPL-3.0 or commercial), the build is unsigned and there is no installer yet.

What the build contains: Electron and `app.asar` (`desktop/electron`), the frontend build, the frozen backend
and `desktop/model_lock.json` (hashes only). What it never contains: the VietOCR model, the PaddleOCR
detector, documents, tokens or machine paths. At run time the recognizer is read from `VIETDOC_MODEL_ROOT`
(or `modelRoot` in `desktop.config.json` in the app's user-data folder) and checked by SHA-256 in
`demo/local_pdf_ocr/backend/contract.py`; the detector is read from the PaddleX folder and checked against
`model_lock.json`. A missing or different file blocks OCR; nothing is ever downloaded.

Keep every build folder **outside the repository** (`<out>` below).

## 1. Packaging environment (once)

A separate virtual environment, never the development `.venv-demo`:

```
py -3.12 -m venv <out>\venv-packaging
<out>\venv-packaging\Scripts\python.exe -m pip install -r packaging\backend\requirements-packaging.txt
```

`requirements-packaging.txt` pins every distribution of the tested build. `paddleocr` is not on it: it is
built from the repository's vendored `PaddleOCR/` folder, exported from Git so no checkout path ends up
in its metadata, with the version the development environment reports:

```
mkdir <out>\src
git archive --format=tar -o <out>\paddleocr-src.tar HEAD PaddleOCR
tar -x -f <out>\paddleocr-src.tar -C <out>\src
set SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PADDLEOCR=3.8.0.dev13+gdab3fe353
<out>\venv-packaging\Scripts\python.exe -m pip install --no-deps <out>\src\PaddleOCR
<out>\venv-packaging\Scripts\python.exe -m pip check
```

## 2. Backend (PyInstaller one-folder)

```
<out>\venv-packaging\Scripts\python.exe -m PyInstaller --noconfirm --clean ^
    --distpath <out>\backend-dist --workpath <out>\backend-build packaging\backend\vietdoc-backend.spec
```

`vietdoc-backend.spec` adds the modules of `runtime_modules.txt` as hidden imports (Paddle, PaddleX and
PaddleOCR import by name) and leaves out what the OCR never uses (build tools, CPython's test suite, the
Baidu/Hugging Face cloud clients, video and linear-algebra libraries, C++ headers and import libraries).
After a dependency change, regenerate `runtime_modules.txt` from real runs of the development server started
the way the desktop app starts it (token on stdin, same arguments) with `-X importtime` added and stderr
saved: once with models through every input kind (born-digital and scanned PDF, PNG, JPG, both modes) and
once without models. Then rebuild and repeat the full regression:

```
<packaging venv python> -I -B -X utf8 -X importtime desktop\python\vietdoc_desktop_server.py <arguments>  2> importtime-1.txt
<packaging venv python> packaging\backend\importtime_modules.py importtime-*.txt > packaging\backend\runtime_modules.txt
```

The spec stops the build if a module it leaves out appears in `runtime_modules.txt`.

## 3. Frontend

```
npm --prefix demo\local_pdf_ocr\frontend ci
npm --prefix demo\local_pdf_ocr\frontend run build
```

## 4. Electron app

electron-builder only accepts relative `extraResources` paths, so link the backend into the ignored
`desktop\out\` folder for the build and remove the link afterwards (`rmdir` removes the link only):

```
mklink /J desktop\out\backend\vietdoc-backend <out>\backend-dist\vietdoc-backend
cd desktop
npx electron-builder --win dir --x64 --config electron-builder.yml --config.directories.output=<out>\electron-out
cmd /c rmdir out\backend\vietdoc-backend
```

- `electron-builder.yml` is the release configuration: fuses set, only the `vi` and `en-US` Chromium locales,
  `default_app.asar` removed, and the smoke test refused (`--smoke-*` makes the app exit with code 2).
- `electron-builder.smoke.yml` makes the **internal test build** that allows the smoke test, for the
  packaged-app regression only. Never hand its output to anyone.

## 5. Checks before any build is used

Unit tests (backend, desktop server, desktop Node), the model-free smoke test, real OCR through the packaged
app on the development documents compared with the A0 baseline, a scan of the build for models, documents
and machine paths, and the license review. Blind documents are never used for any of this.

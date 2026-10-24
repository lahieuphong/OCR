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

The model-free part is automated in `.github/workflows/vietdoc-packaging-ci.yml` (Windows, pull requests into
`main`), with the tools in `packaging/ci/`, which also run locally:

```
<packaging venv python> packaging\ci\scan_bundle.py <out>\electron-out\win-unpacked <report dir> --forbid-string <checkout> --forbid-string %USERPROFILE%
<packaging venv python> packaging\ci\probe_backend.py <out>\electron-out-smoke\win-unpacked\resources <report>\backend-probe.json <synthetic.pdf>
<packaging venv python> packaging\ci\watch_run.py --strict --system32-path --exe "<out>\electron-out-smoke\win-unpacked\VietDoc OCR.exe" ^
    --out <report>\smoke --set VIETDOC_PADDLEX_HOME=<empty dir> -- --user-data-dir=<report>\smoke\userData ^
    --smoke-test=<report>\smoke\smoke --smoke-pdf=<synthetic.pdf>
```

- `scan_bundle.py` fails on model weights, documents, OCR exports, local config, logs, key files, secret-looking
  content or the given machine paths, and writes `manifest.tsv` (path, size, SHA-256 of every file).
- `probe_backend.py` starts the packaged backend alone with the minimal environment and checks the request guard
  (token, `Host`, `Origin`, method), the security headers, the loopback-only listener, the OCR refusal without
  models, the malformed-token refusal, the graceful shutdown and the stdin watchdog.
- `watch_run.py` runs the app once and fails (`--strict`) on any non-loopback connection, any process left after
  exit, a timeout or an unexpected exit code (`--expect-exit 2` for the release build's smoke gate).

CI never has a model, so real OCR stays a manual check on a development machine (`VIETDOC_MODEL_ROOT` pointing at
a verified model folder, the smoke build with `--smoke-pdf=<DEV document>`, the export compared with A0).

## 6. Backend environment

The Electron main process starts the backend with an environment built from scratch
(`desktop/electron/lib/backend-env.js`), never with the user's environment: the Windows essentials (system folders,
temp folders, user profile folders, CPU description), `PATH` = the backend's own folder and `_internal`, then
`System32`, the Windows folder and `Wbem`, `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True`, and `VIETDOC_MODEL_ROOT`
only from the validated configuration. `PYTHON*`, `NODE_OPTIONS`, `PADDLE_PDX_*` sources and caches, `FLAGS_*`,
threading knobs, proxies and every unrelated variable are dropped. Windows itself adds `USERNAME`, `USERDOMAIN` and
`LOGONSERVER` to every child process (libuv), and the PyInstaller bootloader adds its `_PYI_*` variables.

## 7. Offline installer (internal proof of concept)

`desktop/electron-builder.installer.yml` turns the same build into one full offline NSIS installer,
`VietDoc OCR Setup.exe` (Windows x64, per-user in `%LOCALAPPDATA%\Programs\VietDoc OCR`, no administrator
rights, Start Menu shortcut, optional Desktop shortcut, uninstaller). It carries everything OCR needs, the
verified models included, so the target machine needs no Python, Node.js, Git, PaddleOCR, model cache or
`VIETDOC_MODEL_ROOT`. **Internal only and unsigned: never hand it to a third party** while the license review
is open. Nothing is downloaded at install or run time (no `nsis-web`, no update feed, no model download).

The models come from a private staging folder **outside every checkout**, filled from the owner-approved local
sources and checked against the locked SHA-256 values (never committed, never in Git LFS, never a CI artifact or
a GitHub Release asset):

```
<staging>\models\vietocr\onnx\exp_b_width1024\{encoder.onnx, decoder_step.onnx, metadata.json, parity_full.json}
<staging>\models\vietocr\finetuned\exp_b_width1024\weights.pth
<staging>\paddlex\official_models\PP-OCRv6_medium_det\{inference.json, inference.pdiparams, inference.yml}
<staging>\paddlex\{func_ret, locks, temp}\   (empty folders PaddleX would otherwise create in the install folder)
```

Link the backend and both staging folders into the ignored `desktop\out\` folder, build, remove the links:

```
mklink /J desktop\out\backend\vietdoc-backend <out>\backend-dist\vietdoc-backend
mklink /J desktop\out\models  <staging>\models
mklink /J desktop\out\paddlex <staging>\paddlex
cd desktop
npx electron-builder --win nsis --x64 --config electron-builder.installer.yml --config.directories.output=<out>\installer
cmd /c rmdir out\backend\vietdoc-backend & cmd /c rmdir out\models & cmd /c rmdir out\paddlex
```

The packaged app finds `resources\models` and `resources\paddlex` by itself (`desktop/electron/lib/config.js`);
`VIETDOC_MODEL_ROOT`, `VIETDOC_PADDLEX_HOME` or `desktop.config.json` still take precedence when set. The
SHA-256 checks of `contract.py` and `model_lock.json` apply unchanged: a missing or modified bundled file blocks
OCR. `electron-builder.installer-smoke.yml` makes the internal test installer whose app accepts the smoke test,
for the clean-profile regression only. Development and the model-free CI never look for bundled folders.

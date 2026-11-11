# VietDoc OCR — Windows desktop shell (development MVP)

An Electron window around the existing local app: it starts the FastAPI backend of
`demo/local_pdf_ocr/backend` on `127.0.0.1`, serves the built React UI of
`demo/local_pdf_ocr/frontend` from the same origin, shows backend and model status and stops the
backend when the window closes. Recognition, models, limits (15 MB, 6 PDF pages, 12 MP) and the
frozen SHA-256 checks are the backend's own and are not changed here. A PDF-only hybrid H1 mode is
available by explicit selection, with the original OCR retained separately; it is never the default.
See [number review and experimental H1](../docs/OCR_REVIEW_AND_H1.md).

**This is not a standalone build.** It needs, on the same machine: Node.js ≥ 22.12 (for `npm`),
the project's Python venv with the backend dependencies (`.venv-demo`), the frozen VietOCR B1024
files under `<repo>/models/` and the PaddleOCR detector `PP-OCRv6_medium_det` under
`%USERPROFILE%\.paddlex\official_models\`. Nothing is downloaded at run time.

## Run (Windows, CMD)

```bat
cd /d <worktree>\desktop
npm ci
node node_modules\electron\install.js   & rem npm 11 skips install scripts; this fetches the checksum-verified Electron binary
cd ..\demo\local_pdf_ocr\frontend && npm ci && cd ..\..\..\desktop
set VIETDOC_PYTHON=<repo>\.venv-demo\Scripts\python.exe
npm run dev        & rem builds the frontend, then opens the app
npm start          & rem opens the app with the existing build
npm test           & rem Node unit tests (config, security rules, backend process)
```

Both `npm ci` calls install exactly the versions in the committed lockfiles.

The input panel accepts multiple PDFs with a separate method for each file.
Processing the pending list is sequential; results and edits remain separate by
document and method. The **Danh sách văn bản** tab exports the selected results
to one offline XLSX, with STT + the existing 22 metadata fields, Times New Roman
13. See [Excel export and batch behavior](../demo/local_pdf_ocr/frontend/EXCEL_EXPORT.md).

Python tests for the server wrapper (no models needed):

```bat
<repo>\.venv-demo\Scripts\python.exe -m unittest discover -s desktop\python\tests -p "test_*.py"
```

Smoke test (drives the real UI, writes `smoke_report.json`, screenshots and exported files, then
quits; use DEV documents only, never blind documents):

```bat
node scripts\launch.js --smoke-test=<output dir> --smoke-pdf=<dev pdf> [--smoke-timeout=<seconds>]
```

The smoke also runs three PDFs through the real UI and downloads
`downloads/Danh_sach_van_ban.xlsx`. Optionally supply `--smoke-batch-dir=<folder>`
containing the three synthetic metadata PDFs (`officialLetter`, `decision`,
`resolution`). Independently verify the actual download with:

```bat
python scripts\check_excel_export.py "<output dir>\downloads\Danh_sach_van_ban.xlsx" --rows=3 --expected-json="<output dir>\batch_expected.json"
```

The app has one method, the fast header extraction (22 fields from page 1); the smoke checks that
no method choice is offered, runs it on the PDF through the UI, then checks the 22-field form, its
JSON export and the partial TXT/JSON exports. Without models a PDF whose text layer has no
administrative header must be refused (the synthetic CI PDF is), and the form checks then use
`officialLetter.pdf` from `--smoke-batch-dir`; the full-text OCR API must answer 503 too. With the
frozen models and the detector verified, the PDF itself must be extracted. The watchdog stops a run
after `--smoke-timeout` seconds (default 300).

The smoke test only records what it saw; `scripts/check-smoke-report.js` decides PASS/FAIL
(screenshots and preview pixels are warnings only):

```bat
node scripts\check-smoke-report.js <output dir>\smoke_report.json --expect=no-models --with-pdf
node scripts\check-smoke-report.js <output dir>\smoke_report.json --expect=ocr --with-pdf
```

CI (`.github/workflows/vietdoc-electron-ci.yml`, pull requests into main, Windows and Ubuntu) runs
the backend, desktop server and Node tests (a skipped test fails the job), the frontend build, the
tracked-file check and this smoke test with a synthetic PDF made by `scripts/make_synthetic_pdf.py`
(`--expect=no-models`: no model exists on the runners and nothing downloads one). Real OCR is only
verified on a Windows DEV machine with the private model files.

`scripts/launch.js` removes `ELECTRON_RUN_AS_NODE` (set by the VS Code extension host), which would
otherwise make `electron.exe` run as plain Node.

## Configuration

Environment variables win over `desktop/desktop.config.json` (git-ignored; copy
`desktop.config.example.json`):

| Setting | Env | Config key | Default |
|---|---|---|---|
| Python interpreter (absolute) | `VIETDOC_PYTHON` | `python` | `<repo>\.venv-demo\Scripts\python.exe` |
| PaddleX home (detector cache) | `VIETDOC_PADDLEX_HOME` | `paddlexHome` | `%USERPROFILE%\.paddlex` |

The recognizer is read from `<repo>/models/vietocr/...` as pinned in `backend/contract.py`. In a
fresh worktree without `models/`, the app starts, text-layer extraction works and OCR is blocked
with the reason shown in the status window.

## How it is secured

- Windows: `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`, in-memory session,
  no preload in the OCR window; the status window has a 5-function `contextBridge` API whose IPC
  handlers only answer the bundled status page.
- Navigation, redirects, new windows and `<webview>` are blocked outside the app origin; every
  request outside the app origin, its own `blob:`/`data:` URLs and the built-in PDF viewer is
  cancelled; only `clipboard-sanitized-write` is granted; downloads are limited to the app's own
  `blob:` URLs (TXT/JSON export) and go through a save dialog. `plugins: true` is set for the
  built-in PDF viewer used by the preview.
- Backend: bound to `127.0.0.1` on a random port (`SO_EXCLUSIVEADDRUSE`); a per-launch 256-bit
  token is passed on stdin and required on every request (`X-VietDoc-Token`, injected by Electron
  for the app origin only), together with the exact `Host`, `Origin` (if sent), client address and
  method; CSP and other security headers on every response; `no-store` on API responses.
- Offline: before creating the OCR engine the server re-checks the recognizer (`verify_frozen_onnx`)
  and the detector files against `model_lock.json`, and PaddleX model hosters are disabled, so a
  missing model blocks OCR instead of downloading it.
- Lifecycle: the server exits when its stdin closes (Electron gone), on `POST /__desktop__/shutdown`,
  or after an 8 s timeout via `taskkill /T /F`. A crash shows the status window with a restart button.
  After reading the token the server hands the pipe to a private watchdog reader and points fd 0 to
  NUL: on Windows a thread blocked on fd 0 froze native imports (numpy/OpenBLAS), so the first real
  OCR request never finished, and child processes no longer inherit the pipe.

## Layout

```
desktop/
  package.json, package-lock.json   Electron 44.6.0 (dev dependency only)
  model_lock.json                   SHA-256 of recognizer (mirrors contract.py) and detector files
  desktop.config.example.json
  electron/main.js                  windows, lifecycle, smoke test
  electron/preload-app.js           app-window bridge: the app menu (☰) in the page's top bar
  electron/preload-status.js        status-window bridge
  electron/status.{html,css,js}     status window
  electron/lib/app-window.js        Windows title bar in the page, zoom steps, Ctrl +/-/0 (no native menu bar
                                    outside macOS: it cannot follow the app's light look)
  electron/lib/{config,backend,security}.js
  python/vietdoc_desktop_server.py  FastAPI app + static UI + guard + model checks
  python/tests/                     server tests
  scripts/launch.js
  tests/                            Node tests
```

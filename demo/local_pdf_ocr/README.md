# VietDoc OCR — Local Windows demo (experimental)

**Not approved for production.** This is a runnable end-to-end
PDF/PNG/JPEG demo of the frozen VietOCR B1024 recognizer, not a validated
release.

**On main** only the application is versioned: `demo/local_pdf_ocr`
(imported unchanged from `feat/local-pdf-ocr-demo` @ `19e07e5`, without that
branch's history). The research that produced the frozen model — benchmark,
datasets and labels, training, ONNX export and parity tooling — stays on the
`feat/*` research branches and is not part of main. The model files are never
in Git; they live in the ignored `models/` folder and are checked by SHA-256.

## What it does

- React/Vite at http://127.0.0.1:5175.
- FastAPI at http://127.0.0.1:8765; Vite proxies /api.
- PDF/PNG/JPEG upload (15MB maximum, 6 PDF pages, 12MP/page).
- **Explicit extraction method**: for PDFs, select:
  - native_text: PyMuPDF reads the embedded PDF text layer, without
    loading/using any PaddleOCR, VietOCR, or other OCR model.
  - vietocr_ocr: PyMuPDF renders every PDF page (up to 2x, pixel cap),
    PaddleOCR detects lines and VietOCR B always recognizes their images.
  - hybrid_h1: experimental per-line PDF/OCR selection, retaining an
    independent unmodified full OCR baseline. It is never selected automatically.
  - metadata_fast: **Bóc tách nhanh thông tin văn bản**. Inspects the first
    page and extracts only header regions for metadata; it does not OCR the
    remaining pages or appendices. A genuine native header may avoid OCR;
    an electronic-signature text layer alone is not a usable header.
- **Folders and long lists**: "Chọn thư mục" (or dropping a folder) adds every
  PDF/PNG/JPG of the folder and its subfolders, in folder order, with the fast
  header mode preselected; other, empty, >15 MB or already listed files are
  reported as skipped. One method can be applied to all unprocessed documents.
  The queue still sends ONE document at a time to the backend (no parallel OCR):
  it shows progress and remaining time, can pause after the current document and
  continue later, and retries only failed documents. Up to 1000 documents per list.
  metadata_fast accepts PDFs up to 1000 pages (it reads only page 1); the other
  modes keep the 6-page limit.
- PNG/JPEG support full vietocr_ocr or the explicit metadata_fast header mode.
  A missing model blocks required OCR; it never authorizes guessing text.
- Each mode is cached separately per selected file in the frontend;
  after running native_text and vietocr_ocr on the same PDF, click So sánh
  to inspect their texts side-by-side. Fast partial output is kept separate.
- JSON/TXT exports include the selected mode in the filename; JSON
  explicitly reports method, source, engine, and used_ocr.
- PaddleOCR TextDetection model PP-OCRv6_medium_det finds line quadrilaterals.
- PaddleX CropByPolys rectifies line crops as in frozen bake-off.
- RGB/PIL LANCZOS, width round-up-to-10 -> VietOCR B float32 NCHW.
- Exact frozen VietOCR B ONNX encoder/decoder_step; autoregressive
  SOS1 EOS2 and max 129 token generation iterations.
- Source preview, per-page text, copy, TXT and JSON export.

### Fast metadata contract

`POST /api/ocr` accepts `mode=metadata_fast` with the existing upload limits.
`source_page_count` reports the real PDF page count independently of the
returned header page. `inspected_pages` lists pages examined; `processed_pages`
lists only pages actually OCR-processed (empty for a native-only header).
`partial_result=true` means the result is **not full text**. First-page ROIs
expand only when header evidence is incomplete and a taller region can still add
it: growth stops once the body has started (number, date, agency and title sit
above it), after 10 lines past the title or `V/v` line without a body marker (a
notice has no `Căn cứ`), or at the 64-line limit. `fast_metadata.stopped` names the
reason. Missing/obscured headers require review instead of a full-document fallback.
Every mode's result also carries `seal`, a pixel check for a round red seal on the
last pages (see `frontend/METADATA.md`); it never changes the text, and its failure
never fails the request.
The recognizer, detector, tensor preprocessing and decoder limits stay pinned.
Fast OCR verifies the local frozen detector and recognizer before SDK loading,
disables model hosters, and refuses missing/changed files without downloading.
Per-stage `timings_ms` separates inspection, model acquisition/initialization,
rendering, detection, cropping, recognition and selection.

Metadata JSON keeps the exact22-key business schema, and the main Excel sheet
keeps STT +22fields, Times New Roman13. Its source sheet records
`metadata_fast`. Original page count is retained even when only page1 is read.
Fast TXT/JSON and the UI visibly identify partial header content; full-mode
downloads retain their existing behavior. Per-document/per-mode edits and
sequential batch retries are preserved.

The business-type catalog has official codes for Nghị quyết (`01`), Quyết định
(`02`) and Công văn (`22`). Nghị định, Thông báo and Thông tư get the owner's
provisional codes `NĐ`, `TB`, `TT`, marked “mã tạm” and always for review, until
the official catalog is verified; never invent a business code. Issuing dates/agencies must be supported by the
document header, not electronic-signature metadata or incoming stamps.
OCR text, including ambiguous stamp overlaps and diacritics, is not corrected
by dictionary guesses. Confirm those fields against the source before export.

An incoming ("ĐẾN") stamp often touches the subject. When the stamp is read as
its own lines, or its date cell was read on the subject's first line and can be
split off after the cell's value (`Ngày: 03.14./2024, Sửa đổi…`), the subject is
filled with review status and a note naming the stamp. When the stamp's text
cannot be separated from the subject (the cell holds words), the automatic value
remains empty with review status; the complete unverified candidate and original
source evidence remain available next to the field, separately from the 22-key
JSON and Excel values. A standalone word
"đến" is not enough to discard a line. Manual subject edits remain isolated
per document/mode and never overwrite raw OCR text.

The site handles uploads in memory on your own Windows machine, with no
external OCR API or upload storage. On first run PaddleOCR can download
its detection model. The site has no external webfont dependency.

**Important:** 752/752 parity only proved recognizer parity on frozen
reference crops. It did NOT prove end-to-end PDF accuracy, text detection,
crop quality, layout reading order or runtime speed.

## 0. Model preflight

Keep the exact frozen B files in existing local paths:

    models\vietocr\onnx\exp_b_width1024\encoder.onnx
    models\vietocr\onnx\exp_b_width1024\decoder_step.onnx
    models\vietocr\onnx\exp_b_width1024\metadata.json
    models\vietocr\onnx\exp_b_width1024\parity_full.json
    models\vietocr\finetuned\exp_b_width1024\weights.pth

Runtime validates the ONNX graph hashes and frozen full parity PASS, plus
the checkpoint SHA-256:
a2f9d737edca1b2d5d45231b34601a0eb573aafd0fde3202cf6d20601de3edb3.
Never replace B weights or re-open blind test.

## 1. Get the code (Windows CMD)

Use a checkout of main (a fresh clone or a separate `git worktree`), not the
research worktree that holds local training data:

    git clone https://github.com/lahieuphong/OCR.git
    cd OCR

Then place a verified copy of the frozen model files in `models\` as listed
above. Never commit them; `models/` is ignored.

## 2. Create a NEW environment — DO NOT modify .venv-vietocr

    py -3.12 -m venv .venv-demo
    .venv-demo\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
    .venv-demo\Scripts\python.exe -m pip install -r demo\local_pdf_ocr\requirements-demo.txt

PaddlePaddle 3.2.0 CPU and the repository's pinned PaddleOCR source:

    .venv-demo\Scripts\python.exe -m pip install paddlepaddle==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
    set SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PADDLEOCR=3.8.0.dev13+gdab3fe353
    .venv-demo\Scripts\python.exe -m pip install -e PaddleOCR

If Windows/Python has no compatible PaddlePaddle wheel, stop and send the
pip error; do not modify the existing training env or randomly upgrade
the detector. The detection model may need a first-run download.

Model-free tests (the same runner CI uses; it fails on any skipped test):

    .venv-demo\Scripts\python.exe .github\scripts\run_backend_tests.py

## 3. Run backend — CMD terminal A, leave running

    .venv-demo\Scripts\python.exe -m uvicorn demo.local_pdf_ocr.backend.app:app --host 127.0.0.1 --port 8765

Verify http://127.0.0.1:8765/api/health returns
state "ready_to_initialize". This only means the parity report exists;
the first OCR request loads/checks models. If state says
"missing_model_files", investigate before running OCR.

## 4. Run frontend — SECOND CMD terminal B, leave running

Requires Node.js >=20.19 (prefer 22+):

    cd demo\local_pdf_ocr\frontend
    node --version
    npm ci
    npm run dev

`npm ci` installs exactly the versions in `package-lock.json`.

Open http://127.0.0.1:5175/ in Chrome.

## 5. Practical end-to-end demo gate

1. Start with one simple one-page PDF or clear PNG. Large scans may be
   slow because recognition runs line-by-line.
2. Click the "Bắt đầu bóc tách văn bản" button.
3. Inspect Vietnamese diacritics and page order; look for the words
   "chuẩn" and "triển" in actual documents.
4. Save TXT and JSON, compare against actual PDF image.
5. Only then try 21-bct.signed.pdf, 216-tb.signed.pdf,
   738-ttg.signed.pdf and a representative land record.

Only the OCR mode rasterizes the PDF. PDF text mode NEVER runs recognition,
and it fails clearly for scanned PDFs without text. The OCR mode ALWAYS
runs recognition even if the PDF contains perfect embedded text. Neither
mode is used as ground truth for the other during calibration/parity.

If the first PDF fails, save the backend CMD traceback and browser
error, and STOP: do not claim the end-to-end gate passed.

## Existing Windows demo: update code only and restart

If the local demo already runs from a checkout of main, **do not reinstall
or retrain**. Update that checkout, then run the model-free tests:

    git pull --ff-only
    .venv-demo\Scripts\python.exe .github\scripts\run_backend_tests.py

Restart the FastAPI process (Ctrl+C, run the uvicorn command again) and
`npm run dev` (or Ctrl+Shift+R in Chrome) if the UI is stale.
Neither model checkpoint nor ONNX graph needs to be regenerated.

For sample 10333_vpcp-cn_09102026_1-signed.signed.pdf:
1. Select "Text có sẵn trong PDF" and run extraction. This should
   preserve embedded Unicode such as "triển khai thực hiện", "khóa XIII",
   "biến đổi khí hậu", and the signed timestamp ending "+07:00".
2. Switch to "OCR bằng VietOCR B" and run again; this is the independent
   recognizer baseline. Expect much longer execution than text extraction.
3. Click "So sánh" once both results exist. Compare the footer
   "Nơi nhận" and signature blocks as well as the Vietnamese diacritics.
4. Download the JSON of each mode, check method/source/used_ocr fields.
5. Test a **real scan-only** PDF with the text mode: it must fail clearly
   and NOT auto-start OCR. Select OCR deliberately.

The text-layer reader preserves extracted text unchanged but now orders
WHOLE blocks with a conservative spatial algorithm:
- split into vertical bands where the gap exceeds 12 PDF points;
- within a band, traverse the left column before the right ONLY if
  columns are physically separated by at least 6 PDF points;
- otherwise sort the whole band top-to-bottom.
Each block retains its PDF source_block_index in the JSON report.
For the 10333 VPCP sample this moves the digital signature audit block
from the end to the TOP (its physical page location) without changing
its original '+07:00' text. The recipient list and signing title remain
separate, not interleaved line by line.

**Limits:** This spatial heuristic is not universal for tables,
multi-column newsletters or rotated scans, and embedded text is NOT an
independently verified ground truth. Inspect visually before depending
on the output. OCR mode still uses its original line-polygon sorting,
so its reading-order defect is not silently 'fixed' by a text-layer mode.
To improve OCR polygon grouping, preserve and examine a downloadable
*_vietocr_ocr.json report containing each detected polygon.

## OCR reading order gate: conservative split footer (October 10)

A real government PDF OCR report with 50 detected lines showed that a
simple top-to-bottom sort interleaved the recipient list (left) and the
signature block (right). The frozen recognizer is correct at the graph
parity level, but this is a separate **OCR layout error**.

The OCR backend now calls ocr_layout.reorder_split_footer() **after**
VietOCR recognition. It checks polygon geometry ONLY and can regroup
the bottom two columns left-to-right if ALL gates are true:
- a broad full-width text line anchors the end of the page body;
- the following 5+ narrow lines start in the lower 55% of the page,
  occupy <=30% of page height, and include two vertically overlapping
  columns with a gutter >=5.5% of page width;
- there are at least 3 lines in the left column and 2 in the right.

If any check fails, baseline top-to-bottom order is retained.

In the captured JSON (1191x1684px, 50 lines), the last wide anchor is
source line 37. The tail has a measured 114px horizontal gutter,
10 left-column lines (including a paragraph closing line) and 3
right-column lines. The expected footer source-index order is:

    38, 40, 41, 43, 44, 45, 46, 47, 48, 49, 39, 42, 50

The API field pages[].reading_order records the decision including
algorithm, modified, source line indices, gutter, and group sizes.
After a modified sort, pages[].lines[].source_line_index records the
original detection/recognition index. Its line_index becomes the
one-based reconstructed reading-order index. The text, polygon, decoder
limit flag and other recognition fields are never edited.
This change DOES NOT fix mistakes like "triên", "BÔ", "XIIII" or "407:00".

Tests are synthetic and do not expose source customer documents.
Review exported JSON after re-running a document in OCR mode.
The previously exported TXT and JSON will not change retroactively.

The heuristic is deliberately scoped to a split footer. It does not
solve all multi-column layouts, forms, tables, stamps or warped scans.
Any further layout change needs a multi-document OCR layout regression first.

## What CI checks, and what it cannot

`.github/workflows/b1024-app-ci.yml` runs on pull requests into main, on
Windows and Ubuntu: dependency installation from `requirements-demo.txt`
(without PaddlePaddle), Python syntax with warnings as errors, the
model-free backend and frozen-contract tests (a skipped test fails the job),
`npm ci` and the production build, and a check that no model weights,
documents, labels, predictions, private folders or secrets are tracked, in
the tree or in the pull request's commits.

CI never has the frozen model files or the detector, so it does **not**
verify OCR output. That is done locally before merging:

## OCR regression with the private model files (not in CI)

1. Check that `models\` holds the frozen files: `verify_frozen_onnx()` must
   pass (checkpoint, encoder and decoder SHA-256 above), and the detector
   `PP-OCRv6_medium_det` must be the cached copy already used for the A0
   baseline. Nothing may be downloaded.
2. Run `vietocr_ocr` through `/api/ocr` on the permitted DEV PDFs only
   (`10333_vpcp-cn_09102026_1-signed.signed.pdf`, `137-vbhn-bxd.signed.pdf`).
   Never use blind documents.
3. Compare every line with the A0 baseline JSON of the same PDF (same
   polygon, same text). The accepted result is 305/305 lines identical
   (50 + 255), with identical page text and 0 decoder-limit hits.

## Known limitations — NOT deploy-ready

- CPUExecutionProvider only in this local FastAPI demo. Browser WebGPU
  parity 752/752 was a separate experiment and not yet PDF integration.
- No doc rotation, unwarping, or text-line orientation. Detection may
  fail on rotated scans.
- Basic top-to-bottom line ordering, not robust multi-column/table
  layout reconstruction or structured field extraction.
- PDF source preview is the original PDF; detected polygon coordinates
  refer to rendered image pixels, not original PDF points.
- No recognition confidence estimates. No spellchecking/dictionary
  substitutions (diacritics are left untouched).
- 15 MB/6-page/12MP caps; no streaming progress, no API authentication.
  Both processes should remain bound to localhost only.
- The DEV regression above covers two born-digital documents only; a
  complete PDF regression is still needed before any deployment.
- PyMuPDF is AGPL-3.0 (or commercial): resolve its license before
  distributing the app.

Success for this app means "real OCR demo starts and returns the frozen
B1024 output", not a production release.

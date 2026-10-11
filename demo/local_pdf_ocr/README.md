## Experimental document-number review warnings (opt-in; no OCR replacement)

The number-only 5-PDF independent study found NO holdout CER/WER gain from mild
contrast or unsharp transforms. A separate **review-only** feature is now
available on the local website behind an explicit, default-OFF checkbox.

1. Fetch `feat/vietocr-number-review-ui-exp` only for
   `demo/local_pdf_ocr/frontend` and
   `demo/local_pdf_ocr/backend/number_review_preview.py`,
   `demo/local_pdf_ocr/backend/app.py` (only after preserving any local edits).
2. Restart BOTH local FastAPI server (`127.0.0.1:8765`) and Vite
   (`127.0.0.1:5175`) so the new endpoint is available.
3. Choose a PDF and `OCR bằng VietOCR B`, check
   **Bật cảnh báo số văn bản cần kiểm tra (experimental)**, then click
   **Chạy PaddleOCR + VietOCR**. The checkbox does not change the
   OCR request or exported original TXT/JSON.
4. If a number is suspicious (e.g., `1H9`, `RU6`, `2 1`), the
   website opens an original-source crop using a separate no-model API.
   Enter the visibly verified text only if certain, click
   **Lưu xác minh riêng, không sửa OCR**, and download the
   **JSON rà soát riêng** report. Notes exist only in the browser tab
   until exported; they are not a corrected OCR output.
5. When `Số:` is unreadable, a first-page left/header line aligned
   with a right-side dateline is flagged conservatively. When neither
   text nor geometry locates the field, a page-level manual check
   message remains. These are heuristics, not a trained detector.

Do NOT merge the experimental PR, train/replace the frozen ONNX model,
run the frozen blind test or claim recall/precision from the 8
already-evaluated number crops. Approval requires frontend/preview
CI, user-local 5-PDF spot checks and broader independent coverage.

# VietDoc OCR — Local Windows demo (experimental)

**Branch only:** feat/local-pdf-ocr-demo. **Not approved for production.**
This is a first runnable end-to-end PDF/PNG/JPEG demo, not a validated
integration. Main, frozen training files and blind test remain unchanged.

## What it does

- React/Vite at http://127.0.0.1:5175.
- FastAPI at http://127.0.0.1:8765; Vite proxies /api.
- PDF/PNG/JPEG upload (15MB maximum, 6 PDF pages, 12MP/page).
- **Manual extraction method**: for PDFs, select either:
  - native_text: PyMuPDF reads the embedded PDF text layer, without
    loading/using any PaddleOCR, VietOCR, or other OCR model.
  - vietocr_ocr: PyMuPDF renders every PDF page (up to 2x, pixel cap),
    PaddleOCR detects lines and VietOCR B always recognizes their images.
- For PNG/JPEG only vietocr_ocr is available. A scanned PDF without a
  text layer must explicitly use OCR; no automatic fallback occurs.
- Both modes are cached separately per selected file in the frontend;
  after running both, click So sánh to inspect texts side-by-side.
- JSON/TXT exports include the selected mode in the filename; JSON
  explicitly reports method, source, engine, and used_ocr.
- PaddleOCR TextDetection model PP-OCRv6_medium_det finds line quadrilaterals.
- PaddleX CropByPolys rectifies line crops as in frozen bake-off.
- RGB/PIL LANCZOS, width round-up-to-10 -> VietOCR B float32 NCHW.
- Exact frozen VietOCR B ONNX encoder/decoder_step; autoregressive
  SOS1 EOS2 and max 129 token generation iterations.
- Source preview, per-page text, copy, TXT and JSON export.

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

## 1. Fetch ONLY new demo files (Windows CMD)

    cd /d E:\Phong_Nho_IT\OCR
    git fetch origin
    git checkout origin/feat/local-pdf-ocr-demo -- demo/local_pdf_ocr
    git status --short

Do NOT run git pull/reset/switch to avoid overwriting frozen training
inputs with local newline normalization. The checkout above updates only
new demo files, and intentionally leaves your current worktree branch
unchanged. No push or merge to main is required.

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

Model-free tests, then frozen data guard:

    .venv-demo\Scripts\python.exe -m unittest discover -s demo\local_pdf_ocr\backend\tests -p "test_*.py" -v
    .venv-demo\Scripts\python.exe datasets\vietnamese_recognition\training_inputs.py --check

## 3. Run backend — CMD terminal A, leave running

    cd /d E:\Phong_Nho_IT\OCR
    .venv-demo\Scripts\python.exe -m uvicorn demo.local_pdf_ocr.backend.app:app --host 127.0.0.1 --port 8765

Verify http://127.0.0.1:8765/api/health returns
state "ready_to_initialize". This only means the parity report exists;
the first OCR request loads/checks models. If state says
"missing_model_files", investigate before running OCR.

## 4. Run frontend — SECOND CMD terminal B, leave running

Requires Node.js >=20.19 (prefer 22+):

    cd /d E:\Phong_Nho_IT\OCR\demo\local_pdf_ocr\frontend
    node --version
    npm install
    npm run dev

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

If the old local demo already runs, **do not reinstall or retrain**. In
the repo's CMD window, fetch only the changed demo source:

    cd /d E:\Phong_Nho_IT\OCR
    git fetch origin
    git checkout origin/feat/local-pdf-ocr-demo -- demo/local_pdf_ocr

Run updated tests:

    .venv-demo\Scripts\python.exe -m unittest discover -s demo\local_pdf_ocr\backend\tests -p "test_*.py" -v
    .venv-vietocr\Scripts\python.exe datasets\vietnamese_recognition\training_inputs.py --check

Restart the FastAPI process (Ctrl+C, run the uvicorn command again).
Vite normally reloads the frontend after the selective checkout, but
restart npm run dev (or Ctrl+Shift+R in Chrome) if the UI is stale.
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
Keep main unchanged until a multi-document OCR layout regression passes.

## Known limitations — NOT merge/deploy-ready

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
- Need comparison to frozen page-level baseline and complete PDF
  regression before any merge or deployment.

Success for this branch means "real one-page OCR demo starts and returns
correct-looking output" and an initial PDF regression report, not a
production release.


## Experimental region-aware OCR layout v2 (do not merge/deploy)

Branch: feat/local-pdf-ocr-layout-v2, based on feat/local-pdf-ocr-demo.

This version changes only OCR post-processing and detection **diagnostics**,
not the PaddleOCR detector model or VietOCR recognizer. It groups the
geometry of an unambiguous two-column zone found after a broad body line,
regardless of whether the signature is near the bottom or upper half.
It creates page-level reading_order and detection_review metadata.

- Group disjoint left-column lines before right-column signature lines.
- Keep undecidable fragments, such as OCR tokens from a visible stamp,
  in a final zone with layout_region=overprint_review, rather than
  deleting them or inventing corrections. Manual inspection is required.
- Mark suspicious very wide first-page headings and unusually tall
  detections in page.detection_review.flags, **without changing crop or
  recognition results**. This is NOT a trained stamp detector or a
  detection-accuracy improvement.
- Preserve OCR text, quadrilateral coordinates and decoder-limit flags
  for every input line. Never apply Vietnamese spelling replacements.
- Native-text mode now labels scan-dominant PDFs with large displayed
  page rasters and <=12 embedded lines, and reports pages_requiring_ocr,
  native_text_complete, and per-page coverage. This does not auto-run OCR.

Offline replay (not model re-inference) against the four user-supplied
JSON documents covered 10 pages and 417/417 OCR lines. The intended
layout modification applied only on 21-BCT page 2, 216-TB page 6,
738-TTg page 1, and 10333/VPCP-CN page 1. No other page changed order.
The two ambiguous fragments in 738-TTg were kept in overprint_review.
The 3 scan-only PDFs' native-text coverage was 100% full-page raster,
whereas digital 10333 was about 3% largest-image coverage.

No private PDFs, actual OCR outputs, or model weights are committed as
regression fixtures: the in-repo tests use synthetic geometry and PDFs.
Model integration and Windows web build still require a separate local
smoke test. v2 is NOT a replacement for a layout-aware detection model
and cannot split an already-merged header recognition box.

For an already working local Windows demo, from CMD:

    cd /d E:\Phong_Nho_IT\OCR
    git fetch origin
    git checkout origin/feat/local-pdf-ocr-layout-v2 -- demo/local_pdf_ocr
    .venv-demo\Scripts\python.exe -m unittest discover -s demo\local_pdf_ocr\backend\tests -p "test_*.py" -v

If tests pass, restart backend:

    .venv-demo\Scripts\python.exe -m uvicorn demo.local_pdf_ocr.backend.app:app --host 127.0.0.1 --port 8765

Restart frontend from its directory (or ensure it HMR-reloads and rebuilds):

    cd /d E:\Phong_Nho_IT\OCR\demo\local_pdf_ocr\frontend
    npm run build
    npm run dev

Use the same PDFs in OCR mode to verify v2 emits
reading_order.modified=true on the relevant pages. Check every token,
especially the overprint_review fragments in 738-TTg. For native mode
on the three scan PDFs, verify the explicit warning that extracted text
is only an incomplete embedded layer. Keep main and the B checkpoint
untouched. No blind test re-run and no merge.


## Experimental header split — explicit opt-in (branch: feat/local-pdf-ocr-header-split-exp)

Goal: address the concrete detection problem where the two administrative
headers ("BỘ CÔNG THƯƠNG"/"CỘNG HÒA...", etc.) were detected as one wide
PaddleOCR text-line polygon on page 1.

This is NOT a new detector, recognizer checkpoint or production improvement.
The candidate split happens **after PaddleOCR detection and before crop/
recognition**, only when a true dark-pixel-free vertical gutter is present.
It uses image pixel projection and the geometry of the existing polygon,
without looking at the recognized text or PDF text layer.

Requirements for a split include: first-page wide and near-top quadrilateral,
limited rotation, one unambiguous >=18px/1.5%-page-width gutter between
34%-49% of page width, and sufficient ink on both sides. If any condition
fails the original box/crop is retained. If cropping either proposed half
fails, both halves are discarded and the original box is cropped as before.
No text replacement, forced Vietnamese accents or dictionary rules.

The frontend has a checkbox named:
  "Thử tách header hai cột (experimental)"
It defaults **OFF** and is only visible in OCR mode. Check it to run the
candidate split before VietOCR B ONNX recognition; uncheck to run original
OCR Layout v2 unmodified. Native-text mode does not support it.

API: POST /api/ocr multipart/form-data with:
  file=<PDF/image>, mode=vietocr_ocr, split_headers=true|false

JSON output when enabled includes:
- header_split_enabled: true
- pages[].header_split_experiment.enabled / accepted_count /
  accepted_source_detection_indices / extra_line_count
- pages[].lines[].header_split for each half: original_polygon, gap_x,
  gap_px, split_part, source_detection_index.

The experimental run and original baseline are held separately in the
browser and downloaded as distinct files:
  *_vietocr_ocr_header_split.json / TXT (experiment)
  *_vietocr_ocr.json / TXT (baseline)

**Offline proposal validation (no new VietOCR inference):**
- 21-bct page 1: 48-pixel gutter in merged detected line 5
- 216-tb page 1: 39-pixel gutter in merged detected line 6
- 738-ttg page 1: 33-pixel gutter in merged detected line 6
- 10333 VPCP example and other tested pages: NO candidate split.
Three candidate boxes among 417 existing OCR lines across four PDFs
(10 pages). This checks pixel geometry, NOT recognition accuracy.
If each half is successfully cropped, candidate mode is expected to add
one recognized line per document for those three PDFs; it MUST NOT
delete any other line. The real result and accuracy must be confirmed
on the user's Windows environment.

### Safe local Windows update

From CMD, stop both backend and Vite first (Ctrl+C) and preserve any local
edits in demo/local_pdf_ocr before selective checkout:

    cd /d E:\Phong_Nho_IT\OCR
    git fetch origin
    git checkout origin/feat/local-pdf-ocr-header-split-exp -- demo/local_pdf_ocr
    .venv-demo\Scripts\python.exe -m unittest discover -s demo\local_pdf_ocr\backend\tests -p "test_*.py" -v

If **all unit tests OK**, start backend from the repo root:

    .venv-demo\Scripts\python.exe -m uvicorn demo.local_pdf_ocr.backend.app:app --host 127.0.0.1 --port 8765

Open a second CMD:

    cd /d E:\Phong_Nho_IT\OCR\demo\local_pdf_ocr\frontend
    npm run build
    npm run dev

Test first on a single-page file (e.g., 738-ttg) in OCR mode:
1. Checkbox OFF -> run and export original baseline TXT/JSON.
2. Checkbox ON -> run and export experiment TXT/JSON.
3. Inspect split_part left/right under original detected header, and
   compare recognition results and speed against baseline.
4. Run 21-bct and 216-tb only if the first comparison has no regression.
5. Export all six OCR files (3 docs x two variants). Send the pairs for
   side-by-side review. Do not use embedded text as a secret OCR override.
6. Keep this branch unmerged until the split improves tested accuracy
   without regression elsewhere, and a separate end-to-end PDF gate passes.

No re-training, no blind-test rerun, no modification to .venv-vietocr,
no changed ONNX/checkpoint, no main merge or deployment.

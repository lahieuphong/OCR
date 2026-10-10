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

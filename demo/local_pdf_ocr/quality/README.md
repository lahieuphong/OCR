# Recognition quality lab — local experiments only

The quality lab works on already-exported PDF OCR JSON and original PDFs.
It **does not change the website's detector, recognizer, output or weights**.
It does **not** access frozen blind-test data or infer its labels.

## NEW: Click-to-save visual review editor (no manual JSON editing)

After you have **already exported** 72 crops into
`demo/local_pdf_ocr/quality_work/review_01`, **do not rerun prepare_review**.
The new editor works on these exact existing crop PNGs and labels.

From Windows CMD at the repository root:

```bat
cd /d E:\Phong_Nho_IT\OCR
git fetch origin
git checkout origin/feat/vietocr-recognition-quality-exp -- demo/local_pdf_ocr/quality
.venv-demo\Scripts\python.exe -m unittest discover -s demo\local_pdf_ocr\quality\tests -p "test_*.py" -v
.venv-demo\Scripts\python.exe -m demo.local_pdf_ocr.quality.review_server --work-dir demo\local_pdf_ocr\quality_work\review_01
```

Keep the CMD window running. Open **http://127.0.0.1:8766/** in Chrome.
The old `file:///.../index.html` is READ ONLY by design.

At each crop:

1. Inspect the ORIGINAL crop image (not just the OCR prediction).
2. If the OCR line is correct, click **Chữ OCR đúng với ảnh — xác nhận**.
3. If incorrect, edit the pre-filled Vietnamese text and click
   **Lưu bản sửa & tiếp tục**.
4. If a stamp or blur makes the true characters unknowable, click **Bỏ qua**.
   Do not invent missing letters or force a confidence label.
5. The progress counter increases immediately when the local server saves.
   You may stop and restart the server; verified rows remain saved.

Each explicit save changes ONLY `quality_work/review_01/labels.jsonl`
(UTF-8 JSONL), atomically. The editor retains the first pre-edit backup
`labels.jsonl.before_ui.bak`. It refuses if a crop SHA changes, if files
are modified outside the UI while it is open, or if a cross-site request
tries to write labels. It serves ONLY on 127.0.0.1 (not LAN or internet).
PDFs, model checkpoint, ONNX, and the OCR JSON exports remain unchanged.

After the editor shows at least **20 / 72** verified crops, stop it
(Ctrl+C), then run the previous `benchmark --validate-labels-only` command.
Only if that succeeds consider the experimental ONNX crop benchmark.

## Zone-aware QA: manual stamp classification + safe candidate ledger

Branch: `feat/vietocr-zone-aware-qa`, based on
`feat/vietocr-recognition-quality-exp`. **No OCR pipeline changes.**
Keep the original 72 verified lines and 13 corrected labels unchanged.

1. Close the old localhost review editor with Ctrl+C; do NOT rerun
   `prepare_review` or delete `quality_work/review_01`.
2. Update only the offline QA tools:

```bat
cd /d E:\Phong_Nho_IT\OCR
git fetch origin
git checkout origin/feat/vietocr-zone-aware-qa -- demo/local_pdf_ocr/quality
.venv-demo\Scripts\python.exe -m unittest discover -s demo\local_pdf_ocr\quality\tests -p "test_*.py" -v
.venv-demo\Scripts\python.exe -m demo.local_pdf_ocr.quality.review_server --work-dir demo\local_pdf_ocr\quality_work\review_01
```

3. Open `http://127.0.0.1:8766/`. Existing verified texts are preserved.
   Select `Tất cả` if there are no unverified crops, then use the
   **Phân loại vùng ảnh** dropdown and **Lưu phân loại vùng** button.
   Only tag images you have visually inspected; there are no automatic
   rules that decide a printed line is a stamp, or vice versa.
   Suggested priority cases to VISUALLY REVIEW, not pre-label:
   - `216-tb` page 1 line 9: document number over reception-stamp noise
   - `216-tb` page 5 line 14: paragraph plus stamp-overprint fragment
   - `738-ttg` page 1 lines 58 and 59: possible stamp/figure fragments
   - `738-ttg` page 1 line 21: printed Vietnamese diacritic error
   Human reviewers choose among printed_text, stamp_overlap,
   stamp_artifact, handwriting, uncertain. Do not retype or silently
   delete existing references merely to alter the score.

4. When the original benchmark and the targeted `error_analysis.json`
   are already present, run:

```bat
.venv-demo\Scripts\python.exe -m demo.local_pdf_ocr.quality.zone_audit ^
  --work-dir demo\local_pdf_ocr\quality_work\review_01
start "" "E:\Phong_Nho_IT\OCR\demo\local_pdf_ocr\quality_work\review_01\zone_audit.html"
```

   The script reads already saved prediction variants; it DOES NOT
   re-run recognition, detector, PDF rasterization, training or blind test.
   It creates `zone_audit.html` and `zone_audit.json` locally.
   Files contain private verified OCR text and must not be committed.

Important evaluation contract:

- Whole 72-line CER/WER remains unchanged; never erase hard lines
  from official historical measurements.
- Printed-only CER/WER is **optional sensitivity analysis** on
  *explicitly reviewed* printed_text rows, not a new official baseline.
- Unreviewed rows remain **unreviewed**, not automatically printed.
- Candidate ledger highlights local improvements such as `RU6 -> 216`
  but **automatic_choice_approved=false for every line**.
- Stale/modified labels or altered candidate predictions cause a hard stop.
- A 1-line improvement does not justify a general preprocessing rule.
- No main merge, ONNX/checkpoint modification or deployment in this step.

## Verified-error triage after the 72-crop baseline benchmark

If `review_01/benchmark_report.json` exists and its 72 labels have not
changed, analyze the 13 incorrect OCR lines and all line IDs flagged as
candidate regressions in the previous benchmark. No new PDF OCR or crop
export is needed.

```bat
cd /d E:\Phong_Nho_IT\OCR
git fetch origin
git checkout origin/feat/vietocr-recognition-quality-exp -- demo/local_pdf_ocr/quality
.venv-demo\Scripts\python.exe -m unittest discover -s demo\local_pdf_ocr\quality\tests -p "test_*.py" -v

REM Step A: offline analysis, NO model inference
.venv-demo\Scripts\python.exe -m demo.local_pdf_ocr.quality.error_analysis ^
  --work-dir demo\local_pdf_ocr\quality_work\review_01

REM Step B: OPTIONAL — recompute original + 3 variants ONLY on selected crops
.venv-demo\Scripts\python.exe -m demo.local_pdf_ocr.quality.error_analysis ^
  --work-dir demo\local_pdf_ocr\quality_work\review_01 ^
  --with-variants
```

Open `E:\Phong_Nho_IT\OCR\demo\local_pdf_ocr\quality_work\review_01\error_analysis.html`
in Chrome. Each error displays the actual cropped image, verified text,
original VietOCR output, character edit spans, and (with Step B) predictions
and per-line CER/WER error deltas from each transform.

The companion `error_analysis.json` holds the same line-by-line comparison.
Share that JSON if you want the assistant to study the specific mistakes;
it contains PRIVATE human-transcribed text, so share only if appropriate.
The script writes ONLY these two analysis artifacts; it never edits
`labels.jsonl`, `manifest.jsonl`, or `benchmark_report.json`.

Safety gates:

- Revalidate all verified crop SHA256 and label IDs.
- Previous benchmark must be frozen ONNX baseline PASS with the same
  reference text: mismatched per-line labels/summary will STOP.
- Extra line IDs flagged as regressions are included even if baseline
  recognized them correctly (to reveal harmful transforms).
- With Step B, exact baseline is reproduced on *every selected crop*
  before variant predictions are generated.
- Difference categories describe observed text edits, NOT whether the
  problem physically came from a stamp, segmentation, or recognizer.
- Selection-biased samples cannot establish whole-document CER/WER;
  all transform candidates remain NO-GO for deployment.

## Workflow

1. Export image crops with prepare_review. It uses the same PDF raster
   dimensions and PaddleX CropByPolys (quad) as the running web demo.
2. Open quality_work/review_01/index.html and inspect the images.
   Every labels.jsonl row begins with reference=null, verified=false.
3. A reviewer must fill reference with the text truly visible on each
   image and set verified=true. Never copy predictions as ground truth
   without looking at the PDF.
4. The benchmark requires 20+ independently verified crops and checks
   ID provenance and crop SHA256. It first reproduces every baseline
   recognition string using the exact frozen ONNX model. If even one
   differs it stops, without evaluating any image enhancements.
5. Only then compare baseline to mild contrast, unsharp and autocontrast.
   Metrics are micro CER, WER and exact-line rate after Unicode NFC.
   A variant with a new per-line character-error regression is not
   eligible for a larger trial. Nothing is auto-promoted.

These outputs are research only. Candidate scores are NOT proof of
production quality or permission to merge into main.

## Windows CMD — use the EXISTING PDF and experimental JSON files

Stop neither website nor models; no PDF OCR rerun is required.
From the repository root, fetch only the new QA source:

    cd /d E:\Phong_Nho_IT\OCR
    git fetch origin
    git checkout origin/feat/vietocr-recognition-quality-exp -- demo/local_pdf_ocr/quality
    git checkout origin/feat/vietocr-recognition-quality-exp -- demo/local_pdf_ocr/.gitignore
    .venv-demo\Scripts\python.exe -m unittest discover -s demo\local_pdf_ocr\quality\tests -p "test_*.py" -v

Put the three PDFs and their exported experimental JSON files in
E:\OCR_SAMPLES. The paths below are EXAMPLES; replace them if needed:

    .venv-demo\Scripts\python.exe -m demo.local_pdf_ocr.quality.prepare_review ^
      --pair "E:\OCR_SAMPLES\21-bct.signed.pdf" "E:\OCR_SAMPLES\21-bct.signed_vietocr_ocr_header_split.json" ^
      --pair "E:\OCR_SAMPLES\216-tb.signed.pdf" "E:\OCR_SAMPLES\216-tb.signed_vietocr_ocr_header_split.json" ^
      --pair "E:\OCR_SAMPLES\738-ttg.signed.pdf" "E:\OCR_SAMPLES\738-ttg.signed_vietocr_ocr_header_split.json" ^
      --output demo\local_pdf_ocr\quality_work\review_01 --per-page 8 ^
      --focus "Nghi đinh" --focus "RU6/TB"

Open this local file in Chrome to review the crops:

    E:\Phong_Nho_IT\OCR\demo\local_pdf_ocr\quality_work\review_01\index.html

Edit the corresponding labels.jsonl using UTF-8 encoding.
Leave IDs and SHA unchanged. Set reference only after verifying the
printed line and verified=true. Validate the reviewed labels:

    .venv-demo\Scripts\python.exe -m demo.local_pdf_ocr.quality.benchmark ^
      --work-dir demo\local_pdf_ocr\quality_work\review_01 ^
      --validate-labels-only

Only after 20+ rows have been visually reviewed, run the frozen ONNX
recognizer on those existing crops:

    .venv-demo\Scripts\python.exe -m demo.local_pdf_ocr.quality.benchmark ^
      --work-dir demo\local_pdf_ocr\quality_work\review_01

The output is benchmark_report.json (summary and regressed line IDs).
A pre-existing file is never overwritten; create a fresh review
directory for a repeat experiment.

## Fail-closed guardrails

- Existing PDF and JSON filenames must match.
- Page count, rendered page pixel dimensions and polygons are validated.
- Document/report/crop SHA256 are recorded; benchmark checks crop hashes.
- No unreviewed labels count as ground truth.
- No scripts ever overwrite existing review dirs or saved benchmark reports.
- No spelling fixes, private document upload, training, or blind-set access.
- Actual PDFs, line crops, labels and OCR strings must stay LOCAL.

## Gradual merging

This branch is based on feat/local-pdf-ocr-header-split-exp. The first
draft PR targets that branch and contains quality tools, synthetic tests,
a read-only Windows/Linux test workflow and documentation. It must not
merge to main before Windows and Linux tests, model baseline parity and
multi-document real PDF regression. The older experiment branch is 99
commits ahead of main; merging it wholesale would be unsafe. Subsequent
PRs to main should be small, independently gated and reversible.

# Recognition quality lab — local experiments only

The quality lab works on already-exported PDF OCR JSON and original PDFs.
It **does not change the website's detector, recognizer, output or weights**.
It does **not** access frozen blind-test data or infer its labels.

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

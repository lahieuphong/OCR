# Recognition quality lab — local experiments only

The quality lab works on already-exported PDF OCR JSON and original PDFs.
It **does not change the website's detector, recognizer, output or weights**.
It does **not** access frozen blind-test data or infer its labels.

## NEW: Review-risk triage of number fields — no automatic text correction

The independent 5-PDF test found **NO improvement** from contrast_1p15
or unsharp_light on the only remaining header-number error (a handwritten
serial that OCR read with a letter). Both transforms correctly scored
`NO_GO_FOR_LARGER_TRIAL`. Do not apply them automatically.

`number_triage.py` is an additional **model-free, offline** QA utility:
it reads an already existing `number_probe_with_holdout.json`, detects
suspicious numeric serials and disagreement between frozen OCR variants.
The detector **never sees the reference label, PDF filename or external
document number** when creating a flag.

It flags cases such as `Số: 4H7/...`, `Số: RU8/...` and `Số: 3 7/...`;
it does *not* mark `Số: 59 /2025/TT-BXD` suspicious just because there is
a space before the slash. It does not rewrite, normalize, replace or delete
a single OCR character. Missing flags do **not** certify correctness.

Run safely on the existing 3+5 independent-document report:

```bat
cd /d <REPO_ROOT>
git fetch origin
git checkout origin/feat/vietocr-number-review-triage -- demo/local_pdf_ocr/quality
.venv-demo\Scripts\python.exe -m unittest discover -s demo\local_pdf_ocr\quality\tests -p "test_*.py" -v
.venv-demo\Scripts\python.exe -m demo.local_pdf_ocr.quality.number_triage ^
  --input demo\local_pdf_ocr\quality_work\review_01\number_probe_with_holdout.json
```

The output is `review_01/number_triage.json`; this command does not
reload ONNX, rerun OCR, change labels or invoke the blind test. If an
output already exists, provide `--output ...\number_triage_v2.json`
instead of overwriting.

The report separately shows calibration and independent holdout:
- how many incorrect numbers triggered a review flag;
- how many already-correct numbers triggered a review flag;
- how many errors were **not** caught by the heuristic;
- the unchanged OCR text and verified reference for manual inspection.

All scores are on a tiny *selected* header crop set only, and **do not**
represent end-to-end PDF field-detection recall. This work stays in a
Draft PR and is **not** a production feature or merge approval.

## Document-number-only recognition probe (opt-in, no OCR output changes)

The previous 72-crop verified dataset found one specific local improvement:
one document-number crop whose serial OCR had misread as letters was read correctly under BOTH mild
contrast and mild unsharp filtering. This does **not** justify global
contrast or model corrections.

This experimental **number_probe** can now re-evaluate all existing
first-page document-number header crops in \`review_01\`, with the fixed
candidate methods contrast_1p15 and unsharp_light. It uses the unchanged
frozen ONNX recognizer. Field selection depends only on the *baseline*
OCR prefix "Số" (not on a correct transcription), first-page positions,
and line indices. A missed "Số" prefix is a known retrieval false negative,
so this cannot measure document-number field recall.

### Start with your existing verified crops — no PDF OCR rerun

From Windows CMD, after closing any running QA server if needed:

\`\`\`bat
cd /d <REPO_ROOT>
git fetch origin
git checkout origin/feat/vietocr-document-number-probe -- demo/local_pdf_ocr/quality
.venv-demo\Scripts\python.exe -m unittest discover -s demo\local_pdf_ocr\quality\tests -p "test_*.py" -v
.venv-demo\Scripts\python.exe -m demo.local_pdf_ocr.quality.number_probe --calibration-dir demo\local_pdf_ocr\quality_work\review_01
\`\`\`

Output: \`demo/local_pdf_ocr/quality_work/review_01/number_probe.json\`.
If the target exists, the tool STOPS rather than overwrite a previous run.
Use \`--output demo/local_pdf_ocr/quality_work/review_01/number_probe_run_02.json\`
for a new version. The JSON is private (actual confirmed text) and stays
in the gitignored local \`quality_work\` directory.

The current dataset is only **3 PDFs**, so the default result must say
\`INSUFFICIENT_INDEPENDENT_DOCUMENTS\` even if it finds a local gain.
This is intentional. The experiment does not alter the local OCR website.

### Expand with independent document-number scans if available

For each *new and independent* PDF, run the existing local website OCR
and export its untouched \`*_vietocr_ocr_header_split.json\` alongside the
PDF (never edit OCR output). Then make a NEW review directory, e.g.
\`quality_work/review_numbers_02\`, containing only document-number
crops by using \`prepare_review\`'s new selection mode:

\`\`\`bat
.venv-demo\Scripts\python.exe -m demo.local_pdf_ocr.quality.prepare_review ^
  --pair "<SAMPLES_DIR>\new01.pdf" "<SAMPLES_DIR>\new01_vietocr_ocr_header_split.json" ^
  --pair "<SAMPLES_DIR>\new02.pdf" "<SAMPLES_DIR>\new02_vietocr_ocr_header_split.json" ^
  --output demo\local_pdf_ocr\quality_work\review_numbers_02 ^
  --selection document_number ^
  --per-page 8
\`\`\`

Substitute real PDF/JSON filenames! The script does NOT fabricate missing
files, never overwrites existing review packs and never re-runs full OCR.
It records documents missing a candidate instead of hiding them.
\`--per-page\` is the safety maximum: if candidates exceed it, stop
rather than silently skip any matching number line.

Use the same localhost labeling UI on \`review_numbers_02\`:

\`\`\`bat
.venv-demo\Scripts\python.exe -m demo.local_pdf_ocr.quality.review_server --work-dir demo\local_pdf_ocr\quality_work\review_numbers_02
\`\`\`

Verify **every** selected crop by looking at the PDF original, especially
crossed-out, handwritten or stamped document numbers. Never copy the OCR
prediction into the ground truth without checking. If the PDF does not
have visible readable content for a selected crop, do not verify the label;
the probe will fail closed, not guess.

Once there are >=5 distinct new PDFs in holdout with human-verified
number-header crops and not sharing PDF SHA256 with calibration:

\`\`\`bat
.venv-demo\Scripts\python.exe -m demo.local_pdf_ocr.quality.number_probe ^
  --calibration-dir demo\local_pdf_ocr\quality_work\review_01 ^
  --holdout-dir demo\local_pdf_ocr\quality_work\review_numbers_02 ^
  --output demo\local_pdf_ocr\quality_work\review_01\number_probe_with_holdout.json
\`\`\`

The candidate can be marked **eligible for a larger trial only**, not
merge/deployment, when:
- baseline matches EXACTLY on every selected crop;
- calibration and holdout contain no shared PDF SHA;
- at least five separate new holdout PDFs and five verified number crops;
- the holdout achieves strictly fewer character errors, no extra word
  errors and zero *per-line* regressions; and
- the calibration set also has zero line regressions.

No new recognizer weights, checkpoint, browser OCR output or blind tests.
No silent rewriting of Vietnamese diacritics, document numbers, dates,
names, stamps or metadata. Avoid interpreting the 3 calibration PDFs as
independent evidence of candidate accuracy.


## NEW: Click-to-save visual review editor (no manual JSON editing)

After you have **already exported** 72 crops into
`demo/local_pdf_ocr/quality_work/review_01`, **do not rerun prepare_review**.
The new editor works on these exact existing crop PNGs and labels.

From Windows CMD at the repository root:

```bat
cd /d <REPO_ROOT>
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

## NEW: Generate and download zone report inside localhost review UI

Once the four priority regions are manually classified, there is **no
need to type zone_audit commands**. The local review editor has a
`Tạo báo cáo phân tích` button and direct links to the HTML preview
and JSON export. Only the running Windows machine can access them.

1. Stop review_server with Ctrl+C, fetch the updated branch, and restart:

```bat
cd /d <REPO_ROOT>
git fetch origin
git checkout origin/feat/vietocr-zone-aware-qa -- demo/local_pdf_ocr/quality
.venv-demo\Scripts\python.exe -m unittest discover -s demo\local_pdf_ocr\quality\tests -p "test_*.py" -v
.venv-demo\Scripts\python.exe -m demo.local_pdf_ocr.quality.review_server --work-dir demo\local_pdf_ocr\quality_work\review_01
```

2. Visit `http://127.0.0.1:8766/` and scroll to the **Báo cáo kiểm tra
   sau phân loại** panel. Click **Tạo báo cáo phân tích**, then
   **Xem báo cáo trực quan** or **Tải JSON để phân tích tiếp**.

3. The server validates that 20+ crops are human-verified, all hashes
   remain unchanged, the original 72-line frozen ONNX baseline and
   targeted variant predictions match their saved reference text.
   It writes only `zone_audit.html` and `zone_audit.json` locally.
   If anything is stale, the UI shows the error instead of inventing
   a report. If labels change after generation, links reject stale files
   until you click **Tạo báo cáo phân tích** again.

4. If a reviewer marks a crop as `stamp_artifact` but it still carries a
   text-based ground-truth label from initial review, the report flags
   that ID for careful re-review. **It never removes the example or
   silently improves CER/WER.**

The original `benchmark_report.json`, human labels, crop files,
checkpoint, main branch and OCR pipeline are never modified by this action.

## Zone-aware QA: manual stamp classification + safe candidate ledger

Branch: `feat/vietocr-zone-aware-qa`, based on
`feat/vietocr-recognition-quality-exp`. **No OCR pipeline changes.**
Keep the original 72 verified lines and 13 corrected labels unchanged.

1. Close the old localhost review editor with Ctrl+C; do NOT rerun
   `prepare_review` or delete `quality_work/review_01`.
2. Update only the offline QA tools:

```bat
cd /d <REPO_ROOT>
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
   Suggested priority cases to VISUALLY REVIEW, not pre-label (`scan-B`, `scan-C`
   are the local calibration scans of the example command below):
   - `scan-B` page 1 line 9: document number over reception-stamp noise
   - `scan-B` page 5 line 14: paragraph plus stamp-overprint fragment
   - `scan-C` page 1 lines 58 and 59: possible stamp/figure fragments
   - `scan-C` page 1 line 21: printed Vietnamese diacritic error
   Human reviewers choose among printed_text, stamp_overlap,
   stamp_artifact, handwriting, uncertain. Do not retype or silently
   delete existing references merely to alter the score.

4. When the original benchmark and the targeted `error_analysis.json`
   are already present, run:

```bat
.venv-demo\Scripts\python.exe -m demo.local_pdf_ocr.quality.zone_audit ^
  --work-dir demo\local_pdf_ocr\quality_work\review_01
start "" "<REPO_ROOT>\demo\local_pdf_ocr\quality_work\review_01\zone_audit.html"
```

   The script reads already saved prediction variants; it DOES NOT
   re-run recognition, detector, PDF rasterization, training or blind test.
   It creates `zone_audit.html` and `zone_audit.json` locally.
   Files contain private verified OCR text and must not be committed.

Important evaluation contract:

- Whole 72-line CER/WER remains unchanged; never erase hard lines
  from official historical measurements.
- `non_stamp_artifact_sensitivity` separately reports CER/WER after
  omitting ONLY rows explicitly labeled `stamp_artifact` by a reviewer.
  It retains `stamp_overlap`, `uncertain` and `unreviewed` rows and
  is **not** a validated printed-text subset, an official benchmark,
  or evidence that OCR accuracy improved. On the current 72-crop
  dataset, 2 flagged stamp fragments imply a 70-row sensitivity
  calculation; the frozen 72-row baseline remains unchanged.
- Printed-only CER/WER is **optional sensitivity analysis** on
  *explicitly reviewed* printed_text rows, not a new official baseline.
- Unreviewed rows remain **unreviewed**, not automatically printed.
- Candidate ledger highlights local improvements such as a corrected document-number serial
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
cd /d <REPO_ROOT>
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

Open `<REPO_ROOT>\demo\local_pdf_ocr\quality_work\review_01\error_analysis.html`
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

    cd /d <REPO_ROOT>
    git fetch origin
    git checkout origin/feat/vietocr-recognition-quality-exp -- demo/local_pdf_ocr/quality
    git checkout origin/feat/vietocr-recognition-quality-exp -- demo/local_pdf_ocr/.gitignore
    .venv-demo\Scripts\python.exe -m unittest discover -s demo\local_pdf_ocr\quality\tests -p "test_*.py" -v

Put the three PDFs and their exported experimental JSON files in
<SAMPLES_DIR>. The paths below are EXAMPLES; replace them if needed:

    .venv-demo\Scripts\python.exe -m demo.local_pdf_ocr.quality.prepare_review ^
      --pair "<SAMPLES_DIR>\scan-A.pdf" "<SAMPLES_DIR>\scan-A_vietocr_ocr_header_split.json" ^
      --pair "<SAMPLES_DIR>\scan-B.pdf" "<SAMPLES_DIR>\scan-B_vietocr_ocr_header_split.json" ^
      --pair "<SAMPLES_DIR>\scan-C.pdf" "<SAMPLES_DIR>\scan-C_vietocr_ocr_header_split.json" ^
      --output demo\local_pdf_ocr\quality_work\review_01 --per-page 8 ^
      --focus "<word>" --focus "<number pattern>"

Open this local file in Chrome to review the crops:

    <REPO_ROOT>\demo\local_pdf_ocr\quality_work\review_01\index.html

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

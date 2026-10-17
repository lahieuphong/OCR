# Crop-geometry experiment: NO-GO, not integrated

Status: **closed, NO-GO.** The production pipeline (`demo/local_pdf_ocr/backend/`,
B1024) does not use anything in this folder. It still crops every detected line
as before: PaddleX `CropByPolys(det_box_type="quad")`, no padding. The folder is
kept for two reasons:
- it records the experiment;
- `experiments/hybrid_h1` reuses the helpers in `evaluate.py`.

## Question

Does vertical padding around each detected line help the frozen B1024
recognizer? The experiment also tested masking the ink of neighbouring lines.

## Design

- **Only the crop changes.** The following are all the frozen B1024 ones:
  - recognizer weights;
  - preprocessing;
  - greedy decoding;
  - detection polygons and their order.
- **Detection is not rerun.** Polygons come from stored OCR exports.
- **Arms:**
  - **A0**: the baseline crop.
  - **B2, B4, B8, B12**: 2 to 12 px of vertical padding per side, on the
    144-DPI page raster.
  - **C2 to C12**: the same padding, but neighbouring line polygons that fall
    inside the padding are painted with the paper colour.
- **Selection rule.** The rule was registered before any candidate inference
  and is applied on a DEV set of born-digital pages, where the PDF text layer
  is the reference. Human labels are the reference on the scanned regression
  sets.
- **Validity checks:**
  - A0 reproduced the stored baseline text on every line;
  - at zero padding, `geometry.crop_line` matches `CropByPolys` pixel for
    pixel (`tests/test_geometry.py`).

## Result

- **C2 was selected on DEV** (2 px of padding plus masking). It cut character
  errors on the born-digital DEV lines (sign test p < 0.0001), mostly diacritic
  errors.
- **C2 failed the key-field gate:**
  - it introduced new errors in e-mail addresses inside digital-signature
    boxes and in document numbers;
  - on the human-labelled scanned lines it gave no net gain (9 lines improved,
    10 regressed).
- **8 to 12 px of padding was harmful** on every set.
- **Verdict: NO-GO.** No blind evaluation was run, and nothing was integrated.

## Files

| File | Role |
|---|---|
| `geometry.py` | Crop geometry (padding, neighbour mask). Reproduces the PaddleX warp. |
| `analyze_geometry.py` | Measurements taken before the experiment to choose the padding range. |
| `run_experiment.py` | Runs the arms with the frozen recognizer on stored polygons. |
| `evaluate.py` | Paired evaluation and the registered selection rule. H1 reuses its helpers. |
| `tests/` | Geometry parity and evaluation tests, on synthetic data only. |

Inputs (PDFs, OCR exports, labels) and outputs stay outside git, in
`demo/local_pdf_ocr/quality_work/`.

## Tests

```bat
.venv-demo\Scripts\python.exe -m unittest discover -s experiments\crop_geometry\tests -t . -p "test_*.py"
```

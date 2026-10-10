# VietDoc OCR — Local Windows demo (experimental)

**Branch only:** feat/local-pdf-ocr-demo. **Not approved for production.**
This is a first runnable end-to-end PDF/PNG/JPEG demo, not a validated
integration. Main, frozen training files and blind test remain unchanged.

## What it does

- React/Vite at http://127.0.0.1:5175.
- FastAPI at http://127.0.0.1:8765; Vite proxies /api.
- PDF/PNG/JPEG upload (15MB maximum, 6 PDF pages, 12MP/page).
- PyMuPDF renders PDF pages (up to 2x, pixel cap enforced).
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

The PDF is rasterized for actual OCR even when it contains an embedded
text layer. This demo does not silently bypass VietOCR for digital PDF.

If the first PDF fails, save the backend CMD traceback and browser
error, and STOP: do not claim the end-to-end gate passed.

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

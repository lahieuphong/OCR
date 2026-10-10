# VietOCR B width1024: experimental ONNX export + parity

STATUS: NOT DEPLOYED. The Windows RTX 3090 machine has not run these scripts
yet. This work lives only on feat/vietocr-b1024-onnx-parity, not main.

## Frozen model contract

- Selected: phase4_exp_b_width1024; best checkpoint at step 2330
- Checkpoint SHA-256: a2f9d737edca1b2d5d45231b34601a0eb573aafd0fde3202cf6d20601de3edb3
- One-time blind-test CER = 0.006741. Do not rerun blind test.
- PyTorch weights: models/vietocr/finetuned/exp_b_width1024/weights.pth

## Why two graphs

VietOCR vgg_transformer is an autoregressive encoder/decoder, NOT a
PaddleOCR/CTC recognizer. Export creates two graphs:

- encoder.onnx: image float32 [1,3,32,W] → memory float32 [S,1,256].
- decoder_step.onnx: tokens int64 [T,1] and memory [S,1,256] →
  last-token logits float32 [1,233].

Image width, source length and token prefix length are dynamic; batch=1.
The host must implement the pinned greedy decoding algorithm (SOS 1,
EOS 2, max 129 token-generation iterations at decoder limit 128).
Keep RGB conversion, PIL LANCZOS resize, width rounding/clamping and
float32 normalization exactly matching VietOCR process_input. The
metadata.json written by export records these properties and model hashes.

## Commands: Windows CMD at repo root on E:

Fetch only the four new scripts/docs to avoid overwriting locally normalized
training data.

    cd /d E:\Phong_Nho_IT\OCR
    git fetch origin
    git checkout origin/feat/vietocr-b1024-onnx-parity -- datasets/vietnamese_recognition/export_vietocr_onnx.py datasets/vietnamese_recognition/check_vietocr_onnx_parity.py datasets/vietnamese_recognition/tests/test_onnx_export_contract.py datasets/vietnamese_recognition/ONNX_B1024.md

    .venv-vietocr\Scripts\python.exe datasets\vietnamese_recognition\training_inputs.py --check
    .venv-vietocr\Scripts\python.exe -m unittest discover -s datasets\vietnamese_recognition\tests -p "test_onnx_export_contract.py"
    .venv-vietocr\Scripts\python.exe -m pip install "onnx>=1.16,<2" "onnxruntime>=1.20,<2"
    .venv-vietocr\Scripts\python.exe datasets\vietnamese_recognition\export_vietocr_onnx.py

The exporter checks graph syntax and dynamic shape behavior at widths
160, 320, 640, 1024 and decoder prefixes 1, 2, 16 using ONNX Runtime CPU.
ONNX is NOT approved by shape checks alone.

## Parity gates — no blind test

Pre-existing inputs:
- eval_inputs.jsonl: 100 real_val + 552 synthetic_val + 100 bakeoff_regression
- predictions_exp_b_width1024.jsonl
- predictions_exp_b_width1024.meta.json

The checker refuses other splits and mismatched checkpoint metadata. It
verifies each crop's SHA256 before ONNX inference and compares its decoded
Unicode string to the frozen PyTorch/CUDA prediction.

Short diagnostic (does not confer PASS):

    .venv-vietocr\Scripts\python.exe datasets\vietnamese_recognition\check_vietocr_onnx_parity.py --smoke-lines 12

Full gate:

    .venv-vietocr\Scripts\python.exe datasets\vietnamese_recognition\check_vietocr_onnx_parity.py

Success requires ONNX PARITY: PASS, zero text mismatches and zero decoder
limit hits across all 752 non-blind images. The report is at
models/vietocr/onnx/exp_b_width1024/parity_full.json.

Do not weaken exact-text parity if ONNX and PyTorch floating point results
differ. Diagnose any failures without looking at the one-time blind test.

## Future gates

ONNX Runtime WebGPU operator/precision/dynamic-shape compatibility and
host-side greedy decode; end-to-end PaddleOCR detection + VietOCR
recognition; frozen Vietnamese PDF regression, JS/Python CI and Chrome
production validation. No merge to main or deploy until these pass.

If the exporter or parity runner raises an exception on Windows, capture
the full traceback and stop; do not change the trained checkpoint.

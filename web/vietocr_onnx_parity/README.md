# VietOCR B width1024: standalone Chrome/WebGPU parity gate

EXPERIMENTAL: this is NOT the application's PDF OCR pipeline. Nothing in
this directory is approved for deployment. Git branch:
feat/vietocr-b1024-onnx-parity. The existing main is unchanged.

## Ground truth for browser parity

Python ONNX Runtime CPU parity already PASSed on all 752 NON-BLIND image
crops. Its locked model SHA-256 is:
a2f9d737edca1b2d5d45231b34601a0eb573aafd0fde3202cf6d20601de3edb3

Browser parity compares directly against saved PyTorch text predictions,
NOT the one-time blind test. The browser receives a binary float32 tensor
generated with the pinned VietOCR process_input on Windows/Python. This
deliberately avoids comparing a Canvas-resized image (not PIL LANCZOS) with
the Python reference. It only tests graph execution and greedy decoding
compatibility, not JavaScript image preprocessing or PDF extraction.

The staging script validates source checkpoint hashes, both ONNX graph
hashes, the 752-row Python parity PASS report, reference prediction
metadata and 752 frozen non-blind IDs. A blind image cannot enter the
staged fixture set because the manifest split counts are checked.

## Windows CMD: fetch new files only

Run from E:\Phong_Nho_IT\OCR:

    git fetch origin
    git checkout origin/feat/vietocr-b1024-onnx-parity -- datasets/vietnamese_recognition/prepare_vietocr_webgpu_parity.py web/vietocr_onnx_parity

Do not run git reset, pull or re-freeze training inputs. Python and ONNX
weights remain unchanged. Do not merge main.

## First stage: 12 lines

    .venv-vietocr\Scripts\python.exe datasets\vietnamese_recognition\prepare_vietocr_webgpu_parity.py

Expected: WEBGPU FIXTURES READY: 12/752 non-blind lines

Node.js >=20.19 is needed for Vite 7 (prefer Node 22+). Then:

    cd /d E:\Phong_Nho_IT\OCR\web\vietocr_onnx_parity
    node --version
    npm install
    npm test
    npm run dev

Open ONLY http://127.0.0.1:5174/ in Chrome/Edge on Windows.
Select "Chạy WebGPU parity". Do not start the full batch if the first
12 lines have mismatches. In the event of an error, save JSON report and
copy the Chrome DevTools Console error message too.

Expected diagnostic:
WEBGPU_SMOKE_DIAGNOSTIC_PASS, 12 lines, text_mismatches=0,
decoder_limit_hits=0. This is NOT production approval.

## Second stage: 752 lines (only after smoke PASS)

Stop the dev server with Ctrl+C, then:

    cd /d E:\Phong_Nho_IT\OCR
    .venv-vietocr\Scripts\python.exe datasets\vietnamese_recognition\prepare_vietocr_webgpu_parity.py --all
    cd /d E:\Phong_Nho_IT\OCR\web\vietocr_onnx_parity
    npm run dev

Reload the page, run WebGPU parity and export JSON. All 752 lines must
match frozen PyTorch strings with 0 decoder limit hits to pass browser
text parity. Long runtimes are possible because each line is decoded
autoregressively with a complete Transformer prefix at every token.

The browser requests WebGPU only; unsupported ONNX ops can cause
creation/run failures or internal CPU/WASM fallback. Do not equate a
text-parity PASS with proof every kernel ran on GPU. To claim full GPU
execution, also inspect ORT per-operator profiling / fallback behavior
and measure memory, per-line runtime, and device compatibility.

No in-browser image loading / Canvas resizing, PDF detection, layout,
line ordering or OCR production wiring is done at this stage.
Those are separate gates after this stage.

## Private local artifacts

public/artifacts/ contains ONNX graphs and model metadata copied from the
local frozen export. public/fixtures/ contains float32 tensors and a JSON
manifest of reference predictions. Both paths and public/ort,
node_modules, dist, are excluded by this directory's .gitignore.
Never add these directories to git or publish them on any web server
that is accessible outside localhost. No blind-test crops, ground truth,
or blind predictions are staged. No checkpoint weights.pth is copied
to the browser project.

If WebGPU fails, report the full error and stop. Never alter checkpoint,
decoder length, vocab or model selection to make the result pass.

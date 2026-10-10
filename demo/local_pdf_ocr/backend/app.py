"""Local-only FastAPI backend for OCR PDF/PNG/JPEG (not publicly hosted).

Windows: python -m uvicorn demo.local_pdf_ocr.backend.app:app --host 127.0.0.1 --port 8765
"""
from __future__ import annotations

import asyncio
import logging
import time
from functools import lru_cache

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from .contract import MAX_UPLOAD_BYTES, DemoConfigurationError, validate_upload
from .engine import LocalOcrEngine
from .text_layer import extract_pdf_text

logger = logging.getLogger("local_pdf_ocr")
app = FastAPI(
    title="Vietnamese OCR Local Demo (Experimental)",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
_ocr_lock = asyncio.Lock()


@lru_cache(maxsize=1)
def get_engine() -> LocalOcrEngine:
    return LocalOcrEngine()


@app.get("/api/health")
def health():
    from .contract import MODEL_DIR

    return {
        "service": "local-pdf-ocr-demo",
        "state": "ready_to_initialize" if (MODEL_DIR / "parity_full.json").is_file() else "missing_model_files",
        "engine": "paddleocr-det+frozen-vietocr-b-onnx-cpu",
        "modes": ["native_text", "vietocr_ocr"],
        "native_text_ready": True,
        "deployment_approved": False,
    }


@app.post("/api/ocr")
async def ocr(
    file: UploadFile = File(...),
    mode: str = Form("vietocr_ocr"),
    split_headers: bool = Form(False),
):
    # Explicit selection: a PDF's embedded text MUST NOT silently become
    # OCR reference/ground truth, and OCR mode must NEVER auto-skip inference.
    # The explicit True check also preserves direct-call test compatibility:
    # Form(False) is a dependency descriptor, not Python boolean False.
    header_experiment = split_headers is True
    if mode == "native_text" and header_experiment:
        raise HTTPException(status_code=400, detail="Tách header chỉ dùng với chế độ VietOCR.")
    if mode not in {"native_text", "vietocr_ocr"}:
        raise HTTPException(status_code=400, detail="Chế độ không hợp lệ.")
    if _ocr_lock.locked():
        raise HTTPException(status_code=429, detail="Máy đang xử lý tài liệu khác. Vui lòng đợi.")
    filename = file.filename or ""
    try:
        payload = await file.read(MAX_UPLOAD_BYTES + 1)
    finally:
        await file.close()
    try:
        extension = validate_upload(filename, payload)
        if mode == "native_text" and extension != ".pdf":
            raise ValueError("Trích xuất text layer chỉ hỗ trợ PDF. Chọn OCR cho ảnh.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async with _ocr_lock:
        start = time.perf_counter()
        try:
            if mode == "native_text":
                # Intentionally do not initialize PaddlePaddle/ONNX in text mode.
                result = await run_in_threadpool(lambda: extract_pdf_text(payload, filename))
            else:
                if header_experiment:
                    result = await run_in_threadpool(
                        lambda: get_engine().process(payload, filename, split_headers=True)
                    )
                else:
                    result = await run_in_threadpool(
                        lambda: get_engine().process(payload, filename)
                    )
        except DemoConfigurationError as exc:
            logger.error("Model preflight failed: %s", exc)
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("OCR pipeline failed")
            raise HTTPException(
                status_code=503,
                detail=(
                    "Không thể chạy pipeline OCR. Kiểm tra CMD backend: "
                    "PaddleOCR/PaddlePaddle, mô hình detection và ONNX Runtime."
                ),
            ) from exc
        result["request_elapsed_ms"] = round((time.perf_counter() - start) * 1000)
        return JSONResponse(content=result)

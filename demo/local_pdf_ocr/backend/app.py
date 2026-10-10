"""Local-only FastAPI backend for OCR PDF/PNG/JPEG (not publicly hosted).

Windows: python -m uvicorn demo.local_pdf_ocr.backend.app:app --host 127.0.0.1 --port 8765
"""
from __future__ import annotations

import asyncio
import logging
import time
from functools import lru_cache

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from .contract import MAX_UPLOAD_BYTES, DemoConfigurationError, validate_upload
from .engine import LocalOcrEngine

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
        "deployment_approved": False,
    }


@app.post("/api/ocr")
async def ocr(file: UploadFile = File(...)):
    if _ocr_lock.locked():
        raise HTTPException(status_code=429, detail="Máy đang xử lý tài liệu khác. Vui lòng đợi.")
    filename = file.filename or ""
    try:
        payload = await file.read(MAX_UPLOAD_BYTES + 1)
    finally:
        await file.close()
    try:
        validate_upload(filename, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async with _ocr_lock:
        start = time.perf_counter()
        try:
            result = await run_in_threadpool(lambda: get_engine().process(payload, filename))
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

"""Explicit, model-free PDF embedded-text extraction for local demo.

Never invoke PaddleOCR, the VietOCR checkpoint, OCR image rendering, or a
blind-test reference. Output is sourced exclusively from embedded PDF text.

Reading order uses conservative geometric band/column ordering applied
to PDF text blocks. Content-stream indexes are preserved for auditing,
and no characters are ever changed. This is NOT a universal layout engine.
"""
from __future__ import annotations

import time
from pathlib import Path

from .contract import MAX_PDF_PAGES, validate_upload
from .reading_order import order_text_blocks


def extract_pdf_text(raw: bytes, filename: str) -> dict:
    if validate_upload(filename, raw) != ".pdf":
        raise ValueError("Chế độ trích xuất text layer chỉ hỗ trợ tệp PDF.")

    import fitz

    started = time.perf_counter()
    try:
        pdf = fitz.open(stream=raw, filetype="pdf")
    except Exception as error:
        raise ValueError("PDF không thể đọc được hoặc đã hỏng.") from error

    pages = []
    total_lines = 0
    empty_pages = []
    try:
        if pdf.needs_pass:
            raise ValueError("PDF được bảo vệ bằng mật khẩu; hãy cung cấp bản không khóa.")
        if not 1 <= len(pdf) <= MAX_PDF_PAGES:
            raise ValueError(f"Demo hỗ trợ tối đa {MAX_PDF_PAGES} trang PDF mỗi lần.")

        for page_index in range(len(pdf)):
            page_start = time.perf_counter()
            page = pdf[page_index]
            # Read original PDF blocks, without PyMuPDF's linewise sort=True.
            # A conservative geometric sorter reorders WHOLE blocks below.
            blocks = []
            flattened_lines = []
            for source_index, block in enumerate(page.get_text("blocks", sort=False)):
                x0, y0, x1, y1, text, _number, block_type = block[:7]
                if block_type != 0 or not text.strip():
                    continue
                # Keep Unicode and spaces as extracted; do not spellcheck,
                # inject text from OCR, or silently normalize punctuation.
                extracted = text.rstrip("\r\n")
                block_lines = extracted.splitlines()
                if not block_lines:
                    continue
                bbox = [round(float(value), 2) for value in (x0, y0, x1, y1)]
                blocks.append({
                    "source_block_index": source_index,
                    "bbox": bbox,
                    "text": extracted,
                    "line_count": len(block_lines),
                })
            blocks = order_text_blocks(blocks, float(page.rect.width))
            for item in blocks:
                for chunk in item["text"].splitlines():
                    flattened_lines.append({
                        "line_index": len(flattened_lines) + 1,
                        "block_index": item["source_block_index"],
                        "bbox": item["bbox"],
                        "text": chunk,
                    })
            page_text = "\n".join(item["text"] for item in blocks)
            if not page_text.strip():
                empty_pages.append(page_index + 1)
            total_lines += len(flattened_lines)
            pages.append({
                "page": page_index + 1,
                "width": round(float(page.rect.width), 2),
                "height": round(float(page.rect.height), 2),
                "coordinate_system": "pdf_points",
                "reading_order": "spatial_bands_columns_v1",
                "blocks": blocks,
                "lines": flattened_lines,
                "text": page_text,
                "elapsed_ms": round((time.perf_counter() - page_start) * 1000),
            })
    finally:
        pdf.close()

    if len(empty_pages) == len(pages):
        raise ValueError(
            "PDF không có lớp văn bản có thể trích xuất. "
            "Hãy chọn chế độ PaddleOCR + VietOCR để nhận dạng ảnh scan."
        )

    return {
        "filename": Path(filename).name,
        "method": "native_text",
        "source": "embedded_pdf_text_layer",
        "engine": "PyMuPDF",
        "model": None,
        "detection_model": None,
        "recognition_provider": None,
        "used_ocr": False,
        "page_count": len(pages),
        "line_count": total_lines,
        "decoder_limit_hits": None,
        "pages_without_text": empty_pages,
        "pages": pages,
        "text": "\n\n".join(page["text"] for page in pages),
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
        "limitations": [
            "Only the PDF embedded text layer is read; no OCR or visual verification",
            "A scanned page without embedded text stays empty; no automatic fallback",
            "Conservative spatial band/column ordering is not guaranteed for complex layouts",
            "Embedded PDF text may itself be wrong or incomplete",
        ],
        "deployment_approved": False,
    }

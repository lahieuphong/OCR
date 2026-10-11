"""Human-only labels for OCR physical-image region evaluation.

No zone is inferred from OCR text, polygons or language dictionaries.
"""
REVIEWABLE_REGION_TYPES = frozenset({
    "printed_text",
    "stamp_overlap",
    "stamp_artifact",
    "handwriting",
    "uncertain",
})
REGION_TYPE_LABELS = {
    "printed_text": "Chữ in thông thường",
    "stamp_overlap": "Chữ bị con dấu che hoặc đè",
    "stamp_artifact": "Con dấu/hình, không phải dòng văn bản",
    "handwriting": "Chữ viết tay",
    "uncertain": "Không xác định chắc chắn từ ảnh",
}

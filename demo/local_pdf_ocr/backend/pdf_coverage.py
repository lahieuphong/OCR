"""Detect PDFs whose embedded text is only a digital-signature header.

No OCR or network use. A full-page raster with few embedded text lines is
not considered a fully extracted digital PDF.
"""
from __future__ import annotations


def page_raster_coverage(page) -> float:
    """Largest displayed raster's page-area ratio; never add overlapping areas."""
    area = float(page.rect.get_area())
    if area <= 0:
        return 0.0
    coverage = 0.0
    for image in page.get_images(full=True):
        for rect in page.get_image_rects(image[0]):
            clipped = rect & page.rect
            if not clipped.is_empty:
                coverage = max(coverage, float(clipped.get_area()) / area)
    return round(min(1.0, coverage), 4)


def native_page_status(page, text_line_count: int) -> dict:
    fraction = page_raster_coverage(page)
    scan_dominant = fraction >= .65 and text_line_count <= 12
    needs_ocr = scan_dominant or text_line_count == 0
    return {
        "max_raster_page_coverage": fraction,
        "native_text_line_count": text_line_count,
        "scan_dominant": scan_dominant,
        "needs_ocr_for_page_content": needs_ocr,
        "reason": (
            "full_page_scan_with_sparse_embedded_text" if scan_dominant
            else "no_embedded_text" if text_line_count == 0
            else "native_text_available"
        ),
    }

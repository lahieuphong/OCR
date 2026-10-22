"""Write a one-page synthetic PDF with a text layer, for the model-free Electron smoke test in CI.

Generated at run time and never committed (no real document is involved).
Usage: python desktop/scripts/make_synthetic_pdf.py <output.pdf>
"""
import sys

import pymupdf  # PyMuPDF >= 1.24, from demo/local_pdf_ocr/requirements-demo.txt


def main(path: str) -> int:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    lines = [
        "SYNTHETIC TEST DOCUMENT - NOT A REAL RECORD",
        "Decision No. 0000/TEST on the model-free desktop smoke test",
        "1. The application must start, render this page and export its text layer.",
        "2. OCR must be refused because no frozen model is present.",
        "Recipients: - Test agency A; - Test agency B.",
    ]
    for i, text in enumerate(lines):
        page.insert_text((72, 90 + 28 * i), text, fontsize=12)
    doc.save(path)
    doc.close()
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))

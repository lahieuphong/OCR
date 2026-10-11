"""Export auditable OCR line crops from EXISTING local PDF/JSON pairs.

Run from repo root:
  python -m demo.local_pdf_ocr.quality.prepare_review \
    --pair "E:\samples\21-bct.signed.pdf" "E:\samples\21-bct.signed_vietocr_ocr_header_split.json" \
    --output demo\local_pdf_ocr\quality_work\review_01 --per-page 8

This never calls detection, recognition, training, or blind-test code.
Crops use PaddleX CropByPolys, the same operator as the working demo.
Everything generated stays local: scanned fragments must NEVER be committed.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
from pathlib import Path

from .number_fields import select_number_headers


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_id(filename: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_-]+", "_", Path(filename).stem).strip("_")
    return (name or "document")[:48]


def priority(row: dict, flagged: set[int], focus: tuple[str, ...]) -> tuple[int, int]:
    source = int(row.get("source_line_index", row["line_index"]))
    message = str(row.get("text", ""))
    score = (10 if source in flagged else 0)
    if row.get("header_split"):
        score += 10
    if row.get("layout_region") == "overprint_review":
        score += 10
    if any(word.casefold() in message.casefold() for word in focus):
        score += 15
    if row.get("hit_decoder_limit"):
        score += 10
    # Rarer punctuation and very short lines are worth visually checking.
    if message and sum(not c.isalnum() and not c.isspace() for c in message) / len(message) > .12:
        score += 1
    return -score, int(row["line_index"])


def selected_lines(page: dict, *, per_page: int, focus: tuple[str, ...] = ()) -> list[dict]:
    if per_page < 1:
        raise ValueError("per_page must be positive")
    rows = page["lines"]
    flags = page.get("detection_review", {}).get("flags", [])
    flagged = {int(item["source_line_index"]) for item in flags}
    candidates = sorted(rows, key=lambda item: priority(item, flagged, focus))
    return candidates[:per_page]


def render_page(pdf, page_number: int, target_width: int, target_height: int):
    """Reproduce demo.local_pdf_ocr.backend.engine.iter_images rendering."""
    import fitz
    from PIL import Image

    page = pdf[page_number - 1]
    rect = page.rect
    if rect.width <= 0 or rect.height <= 0:
        raise ValueError("Invalid PDF page dimensions")
    zoom = min(2.0, math.sqrt(12_000_000 / (rect.width * rect.height)))
    pix = page.get_pixmap(
        matrix=fitz.Matrix(zoom, zoom),
        colorspace=fitz.csRGB, alpha=False,
    )
    if (pix.width, pix.height) != (target_width, target_height):
        raise ValueError(
            f"STOP: page {page_number} size differs from OCR JSON: "
            f"rendered={(pix.width, pix.height)}, json={(target_width, target_height)}"
        )
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def export_review(pairs: list[tuple[Path, Path]], output: Path, *,
                  per_page: int = 8, focus: tuple[str, ...] = (),
                  selection: str = "priority") -> dict:
    import cv2
    import fitz
    import numpy as np
    from paddlex.inference.pipelines.components import CropByPolys

    if selection not in {"priority", "document_number"}:
        raise ValueError("Unknown crop selection mode")
    if output.exists():
        raise ValueError(f"STOP: output already exists (will not overwrite labels/crops): {output}")
    if not pairs:
        raise ValueError("Provide at least one --pair PDF JSON")
    # Pre-validate all sources BEFORE writing anything.
    inputs = []
    for pdf_path, report_path in pairs:
        if not pdf_path.is_file() or not report_path.is_file():
            raise ValueError(f"Missing PDF or OCR JSON: {pdf_path} {report_path}")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if (report.get("method") != "vietocr_ocr"
                or report.get("used_ocr") is not True
                or Path(report.get("filename", "")).name != pdf_path.name
                or not isinstance(report.get("pages"), list)):
            raise ValueError(f"STOP: incompatible OCR source JSON: {report_path.name}")
        inputs.append((pdf_path, report_path, report, sha256(pdf_path), sha256(report_path)))
    output.mkdir(parents=True)
    crops = output / "crops"
    crops.mkdir()
    cropper = CropByPolys(det_box_type="quad")
    manifest, labels = [], []
    seen = set()
    candidates_by_document = {}
    for pdf_path, report_path, report, pdf_sha, json_sha in inputs:
        doc_id = safe_id(pdf_path.name) + "_" + pdf_sha[:10]
        with fitz.open(pdf_path) as pdf:
            if len(pdf) != len(report["pages"]):
                raise ValueError(f"STOP: PDF page count mismatch: {pdf_path.name}")
            for page_result in report["pages"]:
                page_number = int(page_result["page"])
                if not 1 <= page_number <= len(pdf):
                    raise ValueError("Invalid page number in JSON")
                chosen = (
                    select_number_headers(page_result, limit=per_page)
                    if selection == "document_number"
                    else selected_lines(page_result, per_page=per_page, focus=focus)
                )
                candidates_by_document[doc_id] = (
                    candidates_by_document.get(doc_id, 0) + len(chosen)
                )
                if not chosen:
                    continue
                image = render_page(
                    pdf, page_number, int(page_result["width"]), int(page_result["height"])
                )
                bgr = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
                for line in chosen:
                    line_index = int(line["line_index"])
                    source_index = int(line.get("source_line_index", line_index))
                    identifier = f"{doc_id}_p{page_number:03d}_l{line_index:03d}"
                    if identifier in seen:
                        raise ValueError(f"Duplicate OCR line id {identifier}")
                    seen.add(identifier)
                    poly = np.asarray(line["polygon"], dtype=np.float32)
                    if poly.shape != (4, 2) or not np.isfinite(poly).all():
                        raise ValueError(f"Invalid polygon {identifier}")
                    crop = cropper(bgr, [poly.tolist()])[0]
                    if crop is None or crop.size == 0:
                        raise ValueError(f"Empty crop: {identifier}")
                    name = f"{identifier}.png"
                    destination = crops / name
                    if not cv2.imwrite(str(destination), crop):
                        raise OSError(f"Cannot write: {destination}")
                    record = {
                        "id": identifier,
                        "document": pdf_path.name,
                        "pdf_sha256": pdf_sha,
                        "ocr_report_sha256": json_sha,
                        "page": page_number,
                        "line_index": line_index,
                        "page_width": int(page_result["width"]),
                        "page_height": int(page_result["height"]),
                        "source_line_index": source_index,
                        "polygon": line["polygon"],
                        "ocr_prediction": line["text"],  # NOT ground truth
                        "crop_path": f"crops/{name}",
                        "crop_sha256": sha256(destination),
                        "baseline_method": "PaddleX_CropByPolys_quad",
                        "header_split": bool(line.get("header_split")),
                        "layout_region": line.get("layout_region", ""),
                        "selection_mode": selection,
                    }
                    manifest.append(record)
                    labels.append({
                        "id": identifier,
                        "crop_sha256": record["crop_sha256"],
                        "reference": None,
                        "verified": False,
                    })
    if selection == "document_number":
        # No silent success with all-negative/missed candidates. The original
        # OCR report is preserved; review other PDFs if the heuristic misses.
        if not manifest:
            raise ValueError("No document-number candidates found in the supplied OCR JSON")
    write_jsonl(output / "manifest.jsonl", manifest)
    write_jsonl(output / "labels.jsonl", labels)
    # Read-only offline HTML review; users edit labels.jsonl to supply truth.
    items = []
    for row in manifest:
        image_name = html.escape(row["crop_path"], quote=True)
        label = html.escape(row["id"])
        pred = html.escape(row["ocr_prediction"])
        items.append(f'<article><h3>{label}</h3><img src="{image_name}">'
                     f'<p>OCR (chưa xác minh): {pred}</p></article>')
    (output / "index.html").write_text(
        '<!doctype html><html lang="vi"><meta charset="utf-8">'
        '<title>Review OCR crops (local)</title>'
        '<style>body{font:15px system-ui;margin:3rem;background:#f4f5f8}'
        'article{background:white;padding:1rem;margin:1rem 0;border:1px solid #ddd}'
        'img{max-width:100%;image-rendering:auto}</style>'
        '<h1>OCR crops — chỉ để đối chiếu, chưa phải ground truth</h1>'
        '<p>Đọc ảnh rồi điền reference và verified=true vào labels.jsonl. '
        'Không copy prediction thành ground truth nếu chưa nhìn ảnh.</p>'
        + "".join(items) + "</html>", encoding="utf-8"
    )
    result = {"selected": len(manifest), "documents": len(inputs),
              "selection_mode": selection,
              "selected_by_document": candidates_by_document,
              "documents_without_candidate": [
                  identifier for identifier, amount in candidates_by_document.items()
                  if amount == 0
              ],
              "pages": len({(r["document"], r["page"]) for r in manifest}),
              "verified": 0, "output": str(output), "blind_test_used": False}
    (output / "prepare_summary.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pair", nargs=2, action="append", metavar=("PDF", "OCR_JSON"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-page", type=int, default=8)
    parser.add_argument("--focus", action="append", default=[])
    parser.add_argument(
        "--selection", choices=("priority", "document_number"),
        default="priority", help="Document-number mode selects ALL likely first-page document IDs"
    )
    args = parser.parse_args(argv)
    result = export_review([(Path(a), Path(b)) for a, b in args.pair],
                           args.output, per_page=args.per_page,
                           focus=tuple(args.focus), selection=args.selection)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

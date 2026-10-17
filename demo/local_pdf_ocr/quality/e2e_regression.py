"""Read-only end-to-end regression of the frozen local PDF OCR pipeline.

Run from repo root (Windows CMD):
  .venv-demo\\Scripts\\python.exe -m demo.local_pdf_ocr.quality.e2e_regression ^
    --pair "<SAMPLES_DIR>\\<document>.pdf" "<SAMPLES_DIR>\\<document>_vietocr_ocr_header_split.json" ^
    --output-dir demo\\local_pdf_ocr\\quality_work\\<new_dir>

Re-runs PaddleOCR detection + frozen VietOCR B ONNX (same engine as the
local website, same opt-in header split the export records) and compares
every page and line -- text, polygon, line_index, decoder limit -- with the
EXISTING export. Never overwrites or edits an export, label, model, or
blind-test file. A rerun is a reproduction to compare against, NOT a
replacement baseline.

``--rerun-only PDF`` reruns a PDF whose original export is missing. With
``--samples manifest.json`` (a review pack manifest) the sampled lines are
checked against the rerun. The original export's SHA256 stays unverified.

``--recompare OUTPUT_DIR`` recomputes the comparisons of an earlier run from
its saved rerun files (no OCR) into e2e_regression_summary.recompared.json.
Numbers are compared as values: exports saved by the browser write 356.0 as 356.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from .benchmark import sha256

SCHEMA = "vietdoc_e2e_regression_v1"


def polygon(points) -> list[list[float]]:
    return [[float(value) for value in point] for point in points]


def canonical(value):
    """Numbers as floats: exports saved by the browser turn 356.0 into 356."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items()}
    return [canonical(item) for item in value]


def compare_exports(stored: dict, rerun: dict) -> dict:
    """Line-by-line equality of two OCR exports; timing fields are ignored."""
    text, geometry, index, limit, structure = [], [], [], [], []
    stored_pages, rerun_pages = stored.get("pages", []), rerun.get("pages", [])
    if len(stored_pages) != len(rerun_pages):
        structure.append({"field": "page_count", "stored": len(stored_pages), "rerun": len(rerun_pages)})
    compared = 0
    for old, new in zip(stored_pages, rerun_pages):
        page = old.get("page")
        for field in ("page", "width", "height"):
            if old.get(field) != new.get(field):
                structure.append({"page": page, "field": field, "stored": old.get(field), "rerun": new.get(field)})
        old_lines, new_lines = old.get("lines", []), new.get("lines", [])
        if len(old_lines) != len(new_lines):
            structure.append({"page": page, "field": "line_count",
                              "stored": len(old_lines), "rerun": len(new_lines)})
        for a, b in zip(old_lines, new_lines):
            compared += 1
            where = {"page": page, "line_index": a.get("line_index")}
            if a.get("line_index") != b.get("line_index"):
                index.append({**where, "rerun_line_index": b.get("line_index")})
            if a.get("text") != b.get("text"):
                text.append({**where, "stored": a.get("text"), "rerun": b.get("text")})
            if polygon(a.get("polygon", [])) != polygon(b.get("polygon", [])):
                geometry.append({**where, "stored": a.get("polygon"), "rerun": b.get("polygon")})
            if bool(a.get("hit_decoder_limit")) != bool(b.get("hit_decoder_limit")):
                limit.append(where)
        for field in ("reading_order", "header_split_experiment", "detection_review"):
            if canonical(old.get(field)) != canonical(new.get(field)):
                structure.append({"page": page, "field": field})
    return {
        "pages_stored": len(stored_pages),
        "pages_rerun": len(rerun_pages),
        "lines_compared": compared,
        "structure_mismatches": structure,
        "line_index_mismatches": index,
        "text_mismatches": text,
        "polygon_mismatches": geometry,
        "decoder_limit_mismatches": limit,
        "reproduced_exactly": not (structure or index or text or geometry or limit),
    }


def check_samples(rerun: dict, samples: list[dict]) -> list[dict]:
    """Compare review-pack sample lines (page, line_index, polygon, OCR) with a rerun."""
    lines = {
        (page["page"], line["line_index"]): line
        for page in rerun.get("pages", []) for line in page.get("lines", [])
    }
    results = []
    for sample in samples:
        line = lines.get((sample["page"], sample["line_index"]))
        if line is None:
            status = "line_missing_in_rerun"
        else:
            same_text = line["text"] == sample["ocr_original"]
            same_polygon = polygon(line["polygon"]) == polygon(sample["polygon"])
            status = {
                (True, True): "text_and_polygon_match",
                (False, True): "text_mismatch",
                (True, False): "polygon_mismatch",
                (False, False): "text_and_polygon_mismatch",
            }[(same_text, same_polygon)]
        results.append({
            "id": sample["id"],
            "status": status,
            "rerun_text": None if line is None else line["text"],
            "stored_ocr_original": sample["ocr_original"],
        })
    return results


def environment() -> dict:
    from importlib import metadata

    versions = {}
    for package in ("paddlex", "paddleocr", "paddlepaddle", "onnxruntime", "PyMuPDF", "opencv-python",
                    "opencv-contrib-python", "opencv-python-headless", "Pillow", "numpy"):
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = None
    return versions


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run(pairs: list[tuple[Path, Path]], rerun_only: list[Path], output_dir: Path,
        *, samples_manifest: Path | None = None, split_headers: bool = True) -> dict:
    if output_dir.exists():
        raise ValueError(f"STOP: output already exists (will not overwrite): {output_dir}")
    jobs = []
    for pdf, export in pairs:
        if not pdf.is_file() or not export.is_file():
            raise ValueError(f"Missing PDF or exported OCR JSON: {pdf} {export}")
        stored = json.loads(export.read_text(encoding="utf-8"))
        if stored.get("method") != "vietocr_ocr" or Path(stored.get("filename", "")).name != pdf.name:
            raise ValueError(f"STOP: export does not belong to this PDF: {export.name}")
        jobs.append((pdf, export, stored, bool(stored.get("header_split_enabled"))))
    for pdf in rerun_only:
        if not pdf.is_file():
            raise ValueError(f"Missing PDF: {pdf}")
        jobs.append((pdf, None, None, split_headers))
    if not jobs:
        raise ValueError("Provide at least one --pair or --rerun-only PDF")
    samples = []
    if samples_manifest is not None:
        samples = json.loads(samples_manifest.read_text(encoding="utf-8"))["samples"]

    # The detector would otherwise contact the model host to check sources.
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    from demo.local_pdf_ocr.backend.engine import LocalOcrEngine

    output_dir.mkdir(parents=True)
    engine = LocalOcrEngine()
    summary = {
        "schema": SCHEMA,
        "status": "REGRESSION_EVIDENCE_ONLY_NOT_A_BASELINE",
        "engine_checkpoint_sha256": engine.checkpoint_sha256,
        "environment": environment(),
        "blind_test_used": False,
        "exports_modified": False,
        "documents": [],
    }
    for pdf, export, stored, split in jobs:
        started = time.perf_counter()
        rerun = engine.process(pdf.read_bytes(), pdf.name, split_headers=split)
        elapsed = round(time.perf_counter() - started, 1)
        rerun_path = output_dir / f"{pdf.stem}.rerun.json"
        write_json(rerun_path, rerun)
        record = {
            "document": pdf.name,
            "pdf_sha256": sha256(pdf),
            "split_headers": split,
            "pages": rerun["page_count"],
            "lines": rerun["line_count"],
            "elapsed_seconds": elapsed,
            "rerun_file": rerun_path.name,
            "rerun_sha256": sha256(rerun_path),
        }
        if stored is not None:
            record["stored_export"] = str(export)
            record["stored_export_sha256"] = sha256(export)
            record["comparison"] = compare_exports(stored, rerun)
        else:
            record["stored_export"] = None
            record["stored_export_status"] = "BLOCKED_ORIGINAL_EXPORT_MISSING"
        mine = [sample for sample in samples if sample["document"] == pdf.name]
        if mine:
            record["sample_check"] = check_samples(rerun, mine)
        summary["documents"].append(record)
        # Persist after every document so a long run keeps partial evidence.
        write_json(output_dir / "e2e_regression_summary.json", summary)
        print(f"{pdf.name}: {rerun['page_count']} pages, {elapsed}s", flush=True)
    compared = [d["comparison"] for d in summary["documents"] if "comparison" in d]
    checked = [s for d in summary["documents"] for s in d.get("sample_check", [])]
    summary["totals"] = {
        "documents": len(summary["documents"]),
        "exports_compared": len(compared),
        "exports_reproduced_exactly": sum(c["reproduced_exactly"] for c in compared),
        "lines_compared": sum(c["lines_compared"] for c in compared),
        "text_mismatches": sum(len(c["text_mismatches"]) for c in compared),
        "polygon_mismatches": sum(len(c["polygon_mismatches"]) for c in compared),
        "samples_checked": len(checked),
        "samples_matching_text_and_polygon": sum(s["status"] == "text_and_polygon_match" for s in checked),
    }
    write_json(output_dir / "e2e_regression_summary.json", summary)
    return summary


def recompare(output_dir: Path) -> dict:
    """Recompute the comparisons of an earlier run from its saved rerun files (no OCR)."""
    target = output_dir / "e2e_regression_summary.recompared.json"
    if target.exists():
        raise ValueError(f"STOP: will not overwrite {target}")
    summary = json.loads((output_dir / "e2e_regression_summary.json").read_text(encoding="utf-8"))
    for record in summary["documents"]:
        if not record.get("stored_export"):
            continue
        export, rerun = Path(record["stored_export"]), output_dir / record["rerun_file"]
        if sha256(export) != record["stored_export_sha256"] or sha256(rerun) != record["rerun_sha256"]:
            raise ValueError(f"STOP: stored export or rerun changed since the run: {record['document']}")
        record["comparison"] = compare_exports(json.loads(export.read_text(encoding="utf-8")),
                                               json.loads(rerun.read_text(encoding="utf-8")))
    compared = [d["comparison"] for d in summary["documents"] if "comparison" in d]
    summary["totals"].update({
        "exports_reproduced_exactly": sum(c["reproduced_exactly"] for c in compared),
        "text_mismatches": sum(len(c["text_mismatches"]) for c in compared),
        "polygon_mismatches": sum(len(c["polygon_mismatches"]) for c in compared),
        "structure_mismatches": sum(len(c["structure_mismatches"]) for c in compared),
    })
    summary["recompared_from_saved_reruns"] = True
    write_json(target, summary)
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--recompare", type=Path, metavar="OUTPUT_DIR",
                        help="recompute comparisons of an earlier run from its saved reruns; no OCR")
    parser.add_argument("--pair", nargs=2, action="append", default=[], metavar=("PDF", "OCR_JSON"))
    parser.add_argument("--rerun-only", action="append", default=[], type=Path, metavar="PDF")
    parser.add_argument("--samples", type=Path, help="review pack manifest.json to check sampled lines")
    parser.add_argument("--no-split-headers", action="store_true",
                        help="for --rerun-only PDFs; default reruns with the header split like the exports")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.recompare:
        print(json.dumps(recompare(args.recompare)["totals"], ensure_ascii=False, indent=2))
        return 0
    if args.output_dir is None:
        parser.error("--output-dir is required unless --recompare is given")
    summary = run([(Path(a), Path(b)) for a, b in args.pair], args.rerun_only, args.output_dir,
                  samples_manifest=args.samples, split_headers=not args.no_split_headers)
    print(json.dumps(summary["totals"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

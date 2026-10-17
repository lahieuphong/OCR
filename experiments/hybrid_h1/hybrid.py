"""Candidate H1: per OCR line, the PDF text layer when every trust gate passes, else B1024 unchanged.

Run from repo root (Windows CMD):
  .venv-demo\\Scripts\\python.exe -m experiments.hybrid_h1.hybrid ^
    --sources <crop_dir>\\experiment_sources.json --output-dir <dir>\\h1_runs\\<name> ^
    [--documents 10333 137-vbhn]

No recognizer or detector runs. Polygons, their reading order and every fallback
text come from the stored B1024 output (export or frozen rerun) named in the
sources manifest, checked against its SHA-256. The PDF is read for its text layer
and rendered by the engine's own renderer for the ink checks. No label or
reference file is read. 30.signed.pdf is refused. Outputs go to a new directory;
nothing existing is overwritten.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import platform
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .gates import (
    GATES, assemble, assign_words, base_font_name, covered_words, dark_mask, font_trust, ink_checks, iou,
    normalized_distance, unicode_problem,
)

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
VERSION = "h1_v1"
RESERVED_NAMES = ("30.signed",)
FILLED, STROKED, CLIPPED = 16, 32, 64  # MuPDF FZ_STEXT_FILLED / _STROKED / _CLIPPED span char_flags
SUPERSCRIPT = 1  # MuPDF span flags bit 0 (TEXT_FONT_SUPERSCRIPT)
# First failing gate in this order is the line's fallback_reason.
REASONS = (
    "page_unsupported_geometry", "page_word_segmentation_mismatch", "page_no_text_layer", "page_hidden_text_layer",
    "no_text_layer_words", "word_straddles_polygon", "ambiguous_word_assignment", "multi_line_text",
    "duplicate_text", "overlapping_text", "word_shared_between_polygons",
    "invisible_text", "covered_text", "clipped_text", "superscript_text", "untrusted_font_mapping",
    "replacement_character", "control_or_unassigned_character", "orphan_combining_mark", "non_latin_letter",
    "out_of_vocabulary_character", "word_without_ink", "unexplained_ink",
    "token_count_differs_from_b1024", "gross_mismatch_with_b1024",
)
CODE_FILES = ("gates.py", "hybrid.py")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def code_sha256() -> dict[str, str]:
    return {name: sha256_file(HERE / name) for name in CODE_FILES}


def gates_sha256() -> str:
    return hashlib.sha256(json.dumps(GATES, sort_keys=True).encode("utf-8")).hexdigest()


def refuse_reserved(name: str) -> None:
    if any(token in Path(name).name for token in RESERVED_NAMES):
        raise ValueError(f"STOP: {Path(name).name} is reserved for the blind evaluation and is never read by H1")


# ----------------------------------------------------------- PDF evidence

def document_fonts(doc) -> list[dict]:
    """Every font object of the document (page content, form XObjects and widget appearances)."""
    fonts = []
    for xref in range(1, doc.xref_length()):
        try:
            if doc.xref_get_key(xref, "Type") != ("name", "/Font"):
                continue
            subtype = doc.xref_get_key(xref, "Subtype")[1].lstrip("/")
            basefont = doc.xref_get_key(xref, "BaseFont")
            kind, value = doc.xref_get_key(xref, "Encoding")
            tounicode = doc.xref_get_key(xref, "ToUnicode")[0] != "null"
        except Exception:  # noqa: BLE001 - damaged object: it simply earns no trust
            continue
        if subtype.startswith("CIDFontType"):
            continue  # descendant of a Type0 font, which carries the encoding and ToUnicode
        fonts.append({"xref": xref, "type": subtype, "basefont": basefont[1].lstrip("/") if basefont[0] == "name" else "",
                      "encoding": value.lstrip("/") if kind == "name" else ("" if kind == "null" else "custom"),
                      "has_tounicode": tounicode})
    return fonts


def page_words(page) -> tuple[list[tuple], list[dict]]:
    """Words split on whitespace inside each MuPDF line, with the attributes of their spans.

    Word tuples follow PyMuPDF's (x0, y0, x1, y1, text, block, line, word) plus their index.
    """
    words, attributes = [], []
    raw = page.get_text("rawdict")
    for block_no, block in enumerate(raw["blocks"]):
        if block.get("type") != 0:
            continue
        for line_no, line in enumerate(block["lines"]):
            current: list[tuple[dict, dict]] = []
            word_no = 0

            def flush():
                nonlocal word_no
                if not current:
                    return
                boxes = [c["bbox"] for c, _ in current]
                spans = [s for _, s in current]
                words.append((min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes),
                              max(b[3] for b in boxes), "".join(c["c"] for c, _ in current), block_no, line_no,
                              word_no, len(words)))
                attributes.append({
                    "chars": len(current),
                    "fonts": sorted({s["font"] for s in spans}),
                    "invisible": any(not s["char_flags"] & (FILLED | STROKED) or s["alpha"] == 0 for s in spans),
                    "clipped": any(s["char_flags"] & CLIPPED for s in spans),
                    "superscript": any(s["flags"] & SUPERSCRIPT for s in spans),
                })
                word_no += 1

            for span in line["spans"]:
                for char in span["chars"]:
                    if char["c"].isspace():
                        flush()
                        current = []
                    else:
                        current.append((char, span))
            flush()
    return words, attributes


def polygon_box(polygon: list) -> tuple[float, float, float, float]:
    xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def scale(box, factor: float) -> tuple:
    return tuple(v * factor for v in box[:4])


# ------------------------------------------------------------- decisions

def decide_page(page, rgb, a0_page: dict, zoom: float, trust: dict[str, bool], vocabulary: set[str] | None) -> tuple[dict, list[dict]]:
    """Page record and one decision per A0 line (same order). Reads nothing but the PDF page and A0."""
    started = time.perf_counter()
    words, attributes = page_words(page)
    covered = covered_words(words, page.get_bboxlog())
    for index in covered:
        attributes[index]["covered"] = True
    hidden = {i for i, a in enumerate(attributes) if a["invisible"] or a.get("covered")}
    total_chars = sum(a["chars"] for a in attributes)
    hidden_chars = sum(attributes[i]["chars"] for i in hidden)
    words_text_check = Counter(w[4] for w in page.get_text("words", sort=False)) == Counter(w[4] for w in words)
    geometry_ok = page.rotation == 0 and tuple(page.cropbox) == tuple(page.mediabox)
    dark = dark_mask(rgb)
    visible_boxes_px = [scale(w, zoom) for i, w in enumerate(words) if i not in hidden]

    boxes_pt = [scale(polygon_box(line["polygon"]), 1 / zoom) for line in a0_page["lines"]]
    owners = Counter()
    assigned = []
    for box in boxes_pt:
        inside, problem = assign_words(words, box)
        assigned.append((inside, problem))
        owners.update(w[8] for w in inside)
    covered_lines = sum(any(w[8] not in hidden for w in inside) for inside, _ in assigned)
    lines = len(a0_page["lines"])
    if not geometry_ok:
        page_class, page_reason = "unsupported_geometry", "page_unsupported_geometry"
    elif not words_text_check:
        page_class, page_reason = "word_segmentation_mismatch", "page_word_segmentation_mismatch"
    elif total_chars == 0:
        page_class, page_reason = "no_text_layer", "page_no_text_layer"
    elif hidden_chars / total_chars >= GATES["hidden_min_share"]:
        page_class, page_reason = "hidden_text_layer", "page_hidden_text_layer"
    elif (total_chars - hidden_chars >= GATES["native_min_visible_chars"]
          and lines and covered_lines / lines >= GATES["native_min_line_coverage"]):
        page_class, page_reason = "native_text", None
    else:
        page_class, page_reason = "partial_text", None

    decisions = []
    for line, box_pt, (inside, problem) in zip(a0_page["lines"], boxes_pt, assigned):
        b1024 = line["text"]
        failed, checks = [], {"words": len(inside)}
        if page_reason:
            failed.append(page_reason)
        if not inside:
            failed.append("no_text_layer_words")
        if problem:
            failed.append(problem)
        if any(owners[w[8]] > 1 for w in inside):
            failed.append("word_shared_between_polygons")
        pdf_text, deviation = None, None
        if inside:
            attrs = [attributes[w[8]] for w in inside]
            if any(a["invisible"] for a in attrs):
                failed.append("invisible_text")
            if any(a.get("covered") for a in attrs):
                failed.append("covered_text")
            if any(a["clipped"] for a in attrs):
                failed.append("clipped_text")
            if GATES["reject_superscript"] and any(a["superscript"] for a in attrs):
                failed.append("superscript_text")
            fonts = sorted({f for a in attrs for f in a["fonts"]})
            untrusted = [f for f in fonts if not trust.get(base_font_name(f), False)]
            if untrusted:
                failed.append("untrusted_font_mapping")
            pdf_text, stream_differs = assemble(inside)
            why = unicode_problem(pdf_text, vocabulary)
            if why:
                failed.append(why)
            polygon_px = polygon_box(line["polygon"])
            blank, unexplained = ink_checks(dark, [scale(w, zoom) for w in inside], [a["chars"] for a in attrs],
                                            visible_boxes_px, polygon_px)
            if blank:
                failed.append("word_without_ink")
            if unexplained > GATES["max_unexplained_ink_share"]:
                failed.append("unexplained_ink")
            tokens = (len(pdf_text.split()), len(b1024.split()))
            if GATES["require_same_token_count"] and tokens[0] != tokens[1]:
                failed.append("token_count_differs_from_b1024")
            distance = normalized_distance(pdf_text, b1024)
            if distance > GATES["max_distance_to_b1024"]:
                failed.append("gross_mismatch_with_b1024")
            union = (min(w[0] for w in inside), min(w[1] for w in inside), max(w[2] for w in inside), max(w[3] for w in inside))
            union_px = scale(union, zoom)
            deviation = {"iou": round(iou(union_px, polygon_px), 4),
                         "offset_px": [round(union_px[i] - polygon_px[i], 1) for i in range(4)]}
            checks.update({"fonts": fonts, "untrusted_fonts": untrusted, "stream_order_differs": stream_differs,
                           "words_without_ink": len(blank), "unexplained_ink_share": round(unexplained, 4),
                           "tokens_pdf_b1024": list(tokens), "distance_to_b1024": round(distance, 4)})
        failed = sorted(set(failed), key=REASONS.index)
        decisions.append({
            "line_index": line["line_index"], "source": "b1024" if failed else "pdf_text",
            "fallback_reason": failed[0] if failed else None, "failed_gates": failed,
            "b1024_text": b1024, "pdf_text": pdf_text, "text": b1024 if failed else pdf_text,
            "bbox": [round(v, 1) for v in polygon_box(line["polygon"])], "text_layer_deviation": deviation,
            "checks": checks,
        })
    record = {
        "page": a0_page["page"], "class": page_class, "rotation": page.rotation, "zoom": round(zoom, 6),
        "text_layer_chars": total_chars, "hidden_chars": hidden_chars, "words": len(words),
        "covered_words": len(covered), "words_text_matches_pymupdf": words_text_check,
        "lines": lines, "lines_with_visible_words": covered_lines,
        "visible_words_outside_every_polygon": sum(1 for w in words if w[8] not in hidden and not owners[w[8]]),
        "selected": sum(d["source"] == "pdf_text" for d in decisions),
        "h1_decide_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    return record, decisions


def apply_decisions(export: dict, pages: dict[int, tuple[dict, list[dict]]], meta: dict) -> dict:
    """A0 export with H1 text where selected; every fallback line keeps A0 bytes."""
    result = copy.deepcopy(export)
    for page in result["pages"]:
        record, decisions = pages[page["page"]]
        a0_text_joined = "\n".join(line["text"] for line in page["lines"])
        for line, decision in zip(page["lines"], decisions):
            if line["line_index"] != decision["line_index"]:
                raise ValueError("STOP: decision order differs from the A0 line order")
            if decision["source"] == "b1024" and decision["text"] != line["text"]:
                raise ValueError("STOP: a fallback line would change A0 text")
            line.update({"text": decision["text"], "source": decision["source"],
                         "fallback_reason": decision["fallback_reason"], "page": page["page"], "bbox": decision["bbox"],
                         "model_version": meta["model_version"][decision["source"]],
                         "document_hash": meta["document_hash"], "b1024_text": decision["b1024_text"]})
        if page["text"] == a0_text_joined:
            page["text"] = "\n".join(line["text"] for line in page["lines"])
        elif any(d["source"] == "pdf_text" for d in decisions):
            raise ValueError(f"STOP: A0 page {page['page']} text is not the join of its lines")
        page["h1_page"] = record
    result["text"] = "\n\n".join(page["text"] for page in result["pages"])
    result.update({"method": "hybrid_h1_pdf_text_or_b1024", "h1": meta, "deployment_approved": False})
    return result


def run(sources: list[dict], output_dir: Path) -> dict:
    if output_dir.exists():
        raise ValueError(f"STOP: output already exists (will not overwrite): {output_dir}")
    import fitz
    import numpy as np

    from demo.local_pdf_ocr.backend.contract import MAX_IMAGE_PIXELS, MODEL_DIR
    from demo.local_pdf_ocr.backend.engine import iter_images
    from demo.local_pdf_ocr.quality.vietdoc_review40 import recognizer_vocabulary

    vocabulary = recognizer_vocabulary()
    if not vocabulary:
        raise ValueError("STOP: recognizer vocabulary unavailable")
    model = json.loads((MODEL_DIR / "metadata.json").read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True)
    (output_dir / "documents").mkdir()
    manifest = {
        "schema": "hybrid_h1_run_v1", "version": VERSION, "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "gates": GATES, "gates_sha256": gates_sha256(), "code_sha256": code_sha256(), "pymupdf": fitz.VersionBind,
        "python": platform.python_version(), "b1024_checkpoint_sha256": model["checkpoint_sha256"],
        "recognizer_inference_run": 0, "detector_run": False, "reference_text_used": False, "blind_set_used": False,
        "sources": [],
    }
    decisions_out = (output_dir / "decisions.jsonl").open("x", encoding="utf-8", newline="\n")
    try:
        for source in sources:
            refuse_reserved(source["pdf"])
            refuse_reserved(source["document"])
            pdf, ocr_json = Path(source["pdf"]), Path(source["ocr_json"])
            if sha256_file(pdf) != source["pdf_sha256"] or sha256_file(ocr_json) != source["ocr_json_sha256"]:
                raise ValueError(f"STOP: source changed since the manifest: {source['document']}")
            export = json.loads(ocr_json.read_text(encoding="utf-8"))
            meta = {
                "version": VERSION, "gates_sha256": manifest["gates_sha256"], "code_sha256": manifest["code_sha256"],
                "document_hash": source["pdf_sha256"], "base_ocr_json_sha256": source["ocr_json_sha256"],
                "model_version": {"b1024": f"{export.get('model', 'phase4_exp_b_width1024')}@{model['checkpoint_sha256'][:12]}",
                                  "pdf_text": f"pdf_text_layer@pymupdf-{fitz.VersionBind}+{VERSION}-{manifest['gates_sha256'][:12]}"},
            }
            started = time.perf_counter()
            raw = pdf.read_bytes()
            render_started = time.perf_counter()
            rasters = dict(iter_images(raw, ".pdf"))  # the engine's exact raster
            render_ms = (time.perf_counter() - render_started) * 1000
            results = {}
            with fitz.open(stream=raw, filetype="pdf") as doc:
                fonts = document_fonts(doc)
                trust = font_trust(fonts)
                for a0_page in export["pages"]:
                    image = rasters[a0_page["page"]]
                    if (image.width, image.height) != (a0_page["width"], a0_page["height"]):
                        raise ValueError(f"STOP: raster differs from the export: {source['document']} p{a0_page['page']}")
                    fpage = doc[a0_page["page"] - 1]
                    zoom = min(2.0, math.sqrt(MAX_IMAGE_PIXELS / (fpage.rect.width * fpage.rect.height)))
                    results[a0_page["page"]] = decide_page(fpage, np.asarray(image), a0_page, zoom, trust, vocabulary)
            h1 = apply_decisions(export, results, meta)
            elapsed_ms = (time.perf_counter() - started) * 1000
            name = Path(source["document"]).stem
            (output_dir / "documents" / f"{name}.h1.json").write_text(json.dumps(h1, ensure_ascii=False, indent=1), encoding="utf-8")
            for page_no, (record, decisions) in results.items():
                for decision in decisions:
                    decisions_out.write(json.dumps({"key": f"{source['document']}|{page_no}|{decision['line_index']}",
                                                    "set": source["set"], "document": source["document"], "page": page_no,
                                                    "page_class": record["class"], **decision}, ensure_ascii=False) + "\n")
            pages = [record for record, _ in results.values()]
            manifest["sources"].append({
                "document": source["document"], "set": source["set"], "pdf_sha256": source["pdf_sha256"],
                "ocr_json_sha256": source["ocr_json_sha256"], "h1_json_sha256": sha256_file(output_dir / "documents" / f"{name}.h1.json"),
                "fonts": fonts, "font_trust": trust, "pages": pages,
                "lines": sum(p["lines"] for p in pages), "selected": sum(p["selected"] for p in pages),
                "a0_elapsed_ms": export.get("elapsed_ms"), "a0_page_elapsed_ms": [p.get("elapsed_ms") for p in export["pages"]],
                "h1_render_ms": round(render_ms, 1), "h1_total_ms": round(elapsed_ms, 1),
            })
            print(f"{source['document']}: {manifest['sources'][-1]['selected']}/{manifest['sources'][-1]['lines']} lines from the text layer, "
                  f"{Counter(p['class'] for p in pages)}, {elapsed_ms:.0f} ms", flush=True)
    finally:
        decisions_out.close()
        manifest["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        (output_dir / "h1_run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


def select_sources(sources: list[dict], documents: list[str]) -> list[dict]:
    chosen = [s for s in sources if not documents or any(s["document"].startswith(d) for d in documents)]
    if documents and len(chosen) != len(documents):
        raise ValueError(f"STOP: --documents matched {len(chosen)} sources for {len(documents)} names")
    return chosen


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--documents", nargs="*", default=[], help="document name prefixes; default all")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = json.loads(args.sources.read_text(encoding="utf-8"))
    sources = select_sources(manifest["sources"], args.documents)
    result = run(sources, args.output_dir)
    print(json.dumps({"sources": len(result["sources"]), "lines": sum(s["lines"] for s in result["sources"]),
                      "selected": sum(s["selected"] for s in result["sources"])}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

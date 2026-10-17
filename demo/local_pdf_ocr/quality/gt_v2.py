"""Ground truth v2: blind re-check queues, a fail-closed v2 label builder, text-layer report.

Run from repo root (Windows CMD):
  .venv-demo\\Scripts\\python.exe -m demo.local_pdf_ocr.quality.gt_v2 queue ^
    --pack-dir vietdoc_5pdf_quality_review_40 --labels "<LABELS_DIR>\\vietdoc_5pdf_verified_labels.json" ^
    --pdf-dir "<SAMPLES_DIR>" ^
    --v1-dir demo\\local_pdf_ocr\\quality_work\\vietdoc_5pdf_review40_eval_v1 --output-dir <new_dir>\\gt_v2

``queue`` writes an offline page that shows ONLY the line image until the
reviewer has typed and locked a blind transcription. OCR, the v1 label and the
PDF text layer are revealed afterwards, for adjudication; changing the blind
text after the reveal needs a written reason. ``train-queue`` does the same for
quarantined training labels. ``labels-v2`` validates a reviewer export and
writes labels v2 only when every required item carries a valid human decision;
otherwise it writes a BLOCKED report. ``quarantine-review`` releases a
quarantined training label only when that export verified it exactly as it
stands. ``textlayer`` compares OCR with the v1 label and with the PDF text
layer line by line.

Nothing here edits labels v1, reruns OCR, fills a transcription, or corrects
text from context. Every output is a new file.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from .benchmark import distance, metrics, nfc, sha256

QUEUE_SCHEMA = "vietdoc_blind_queue_v1"
EXPORT_SCHEMA = "vietdoc_blind_review_export_v1"
LABELS_V2_SCHEMA = "vietdoc_holdout_manual_review_v2"
REGIONS = ("printed_text", "handwriting", "stamp_overlap", "stamp_artifact", "uncertain")
FINAL_STATUSES = ("verified", "uncertain", "not_text")
CONTEXT_PX = (24, 28)  # horizontal, vertical context around the polygon for the human view
MARKER_GUTTER = 14


# ------------------------------------------------------------------ images

def png_bytes(image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def with_marker(image, top: int, bottom: int):
    """Prepend a left gutter whose red bar marks the rows of the target line."""
    from PIL import Image, ImageDraw

    canvas = Image.new("RGB", (image.width + MARKER_GUTTER, image.height), (255, 255, 255))
    canvas.paste(image.convert("RGB"), (MARKER_GUTTER, 0))
    ImageDraw.Draw(canvas).rectangle((3, max(0, top), MARKER_GUTTER - 5, min(image.height - 1, bottom)),
                                     fill=(214, 40, 40))
    return canvas


def context_view(pdf_path: Path, page_number: int, polygon: list) -> bytes:
    """The line in its page context (same zoom-2.0 raster as the OCR) with a marker."""
    import fitz
    from PIL import Image

    with fitz.open(pdf_path) as pdf:
        page = pdf[page_number - 1]
        zoom = min(2.0, math.sqrt(12_000_000 / (page.rect.width * page.rect.height)))
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csRGB, alpha=False)
        raster = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
    left, top = max(0, int(min(xs)) - CONTEXT_PX[0]), max(0, int(min(ys)) - CONTEXT_PX[1])
    right = min(raster.width, int(math.ceil(max(xs))) + CONTEXT_PX[0])
    bottom = min(raster.height, int(math.ceil(max(ys))) + CONTEXT_PX[1])
    view = raster.crop((left, top, right, bottom))
    return png_bytes(with_marker(view, int(min(ys)) - top, int(math.ceil(max(ys))) - top))


def framed_crop(path: Path) -> bytes:
    """A stored training crop; the whole image is the line, so the bar spans it."""
    from PIL import Image

    with Image.open(path) as image:
        return png_bytes(with_marker(image, 0, image.height - 1))


# ------------------------------------------------------------------ queues

def eval_items(pack_dir: Path, labels_path: Path, pdf_dir: Path, v1_dir: Path) -> list[dict]:
    """All 40 pack lines; the v1 recheck rows are required, the rest optional."""
    manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    labels = {r["id"]: r for r in json.loads(labels_path.read_text(encoding="utf-8"))["labels"]}
    with (v1_dir / "manual_recheck_required.csv").open(encoding="utf-8-sig", newline="") as stream:
        recheck = {row["id"]: row for row in csv.DictReader(stream)}
    integrity = json.loads((v1_dir / "label_integrity_report.json").read_text(encoding="utf-8"))
    layer = {s["id"]: s["text_layer"]["text_layer"] for s in integrity["samples"] if s.get("text_layer")}
    items = []
    for sample in manifest["samples"]:
        pdf_path = pdf_dir / sample["document"]
        if sha256(pdf_path) != sample["pdf_sha256"]:
            raise ValueError(f"STOP: PDF hash differs: {pdf_path}")
        review = labels[sample["id"]]["review"]
        items.append({
            "id": sample["id"], "kind": "eval40", "required": sample["id"] in recheck,
            "priority": recheck.get(sample["id"], {}).get("priority", "optional"),
            "document": sample["document"], "page": sample["page"], "line_index": sample["line_index"],
            "image": context_view(pdf_path, sample["page"], sample["polygon"]),
            "reveal": {"v1_label": review.get("reference"), "v1_status": review.get("status"),
                       "v1_region": review.get("region"), "ocr_original": sample["ocr_original"],
                       "pdf_text_layer": layer.get(sample["id"]),
                       "evidence": recheck.get(sample["id"], {}).get("evidence", "")},
        })
    return items


def train_items(audit_rows: list[dict], dataset_dir: Path) -> list[dict]:
    """Quarantined training/validation labels; only the stored crop exists."""
    items = []
    for row in audit_rows:
        crop = dataset_dir / row["image_path"]
        if sha256(crop) != row["crop_sha256"]:
            raise ValueError(f"STOP: training crop hash differs: {crop}")
        items.append({
            "id": row["id"], "kind": "train_label", "required": True, "priority": "high",
            "document": row["source_document"], "page": int(row["page"]), "line_index": int(row["line_index"]),
            "image": framed_crop(crop),
            "reveal": {"v1_label": row["text"], "v1_status": "verified", "v1_region": "",
                       "ocr_original": None, "pdf_text_layer": None, "evidence": row["evidence"]},
        })
    return items


def write_queue(items: list[dict], output_dir: Path, queue_id: str, title: str) -> dict:
    """Queue JSON (for the builder) + offline HTML (for the reviewer). Never overwrites."""
    queue_path, html_path = output_dir / f"{queue_id}.queue.json", output_dir / f"{queue_id}.review.html"
    for path in (queue_path, html_path):
        if path.exists():
            raise ValueError(f"STOP: will not overwrite {path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    queue = {
        "schema": QUEUE_SCHEMA, "queue_id": queue_id, "title": title,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "protocol": "blind transcription locked before any reveal; post-reveal change needs a reason",
        "items": [{**{k: v for k, v in item.items() if k != "image"},
                   "image_sha256": hashlib.sha256(item["image"]).hexdigest()} for item in items],
    }
    queue_bytes = json.dumps(queue, ensure_ascii=False, indent=2).encode("utf-8")
    queue_path.write_bytes(queue_bytes)
    queue_sha = hashlib.sha256(queue_bytes).hexdigest()
    page_items = [{
        "id": item["id"], "kind": item["kind"], "required": item["required"], "priority": item["priority"],
        "where": f"{item['document']} · tr.{item['page']} · dòng {item['line_index']}",
        "image": "data:image/png;base64," + base64.b64encode(item["image"]).decode(),
        "image_sha256": hashlib.sha256(item["image"]).hexdigest(),
        # Revealed only after the blind entry is locked; encoded so it is not legible at a glance.
        "sealed": base64.b64encode(json.dumps(item["reveal"], ensure_ascii=False).encode("utf-8")).decode(),
    } for item in items]
    config = {"queue_id": queue_id, "queue_sha256": queue_sha, "title": title, "items": page_items,
              "regions": list(REGIONS), "export_schema": EXPORT_SCHEMA}
    html_path.write_text(REVIEW_PAGE.replace("__CONFIG__", json.dumps(config, ensure_ascii=False)),
                         encoding="utf-8")
    return {"queue": str(queue_path), "html": str(html_path), "queue_sha256": queue_sha,
            "items": len(items), "required": sum(item["required"] for item in items)}


# --------------------------------------------------------------- labels v2

def validate_export(queue: dict, queue_sha: str, export: dict) -> tuple[dict, list[str], list[str]]:
    """Decisions that are valid, problems that block, and required ids still missing."""
    problems, decisions = [], {}
    if export.get("schema") != EXPORT_SCHEMA:
        problems.append("export schema is not " + EXPORT_SCHEMA)
    if export.get("queue_id") != queue["queue_id"] or export.get("queue_sha256") != queue_sha:
        problems.append("export belongs to another queue (queue id or SHA256 differs)")
    if not str(export.get("reviewer", "")).strip():
        problems.append("reviewer name missing")
    by_id = {item["id"]: item for item in queue["items"]}
    for identifier, entry in (export.get("items") or {}).items():
        item = by_id.get(identifier)
        if item is None:
            problems.append(f"{identifier}: not in the queue")
            continue
        blind, final = entry.get("blind") or {}, entry.get("final") or {}
        if not blind.get("locked_at"):
            continue  # opened but never locked: not a decision
        where = f"{identifier}:"
        if entry.get("image_sha256") != item["image_sha256"]:
            problems.append(f"{where} image differs from the queue")
            continue
        if blind.get("status") not in ("typed", "unreadable", "not_text"):
            problems.append(f"{where} unknown blind status")
            continue
        if not final.get("decided_at"):
            continue
        if entry.get("revealed_at") and entry["revealed_at"] < blind["locked_at"]:
            problems.append(f"{where} reveal happened before the blind entry was locked")
            continue
        status, text = final.get("status"), final.get("text")
        if status not in FINAL_STATUSES or final.get("region") not in REGIONS:
            problems.append(f"{where} unknown final status or region")
            continue
        if blind["status"] != "typed" and status == "verified":
            problems.append(f"{where} a line unreadable in the blind pass cannot become verified after the reveal")
            continue
        if status == "verified":
            if not isinstance(text, str) or not text.strip() or text != text.strip() or "\n" in text or text != nfc(text):
                problems.append(f"{where} verified text must be one non-empty NFC line without outer spaces")
                continue
            if nfc(text) != nfc(blind.get("text") or "") and not str(final.get("note", "")).strip():
                problems.append(f"{where} final text differs from the blind entry without a written reason")
                continue
        elif text:
            problems.append(f"{where} {status} must not carry a reference text")
            continue
        decisions[identifier] = {"blind": blind, "final": final, "revealed_at": entry.get("revealed_at")}
    missing = [i["id"] for i in queue["items"] if i["required"] and i["id"] not in decisions]
    return decisions, problems, missing


def build_labels_v2(labels_v1: Path, queue_path: Path, export_path: Path, output_dir: Path) -> dict:
    """labels_v2.json only when the export is valid and complete; otherwise a BLOCKED report."""
    target, blocked = output_dir / "labels_v2.json", output_dir / "labels_v2_BLOCKED.json"
    for path in (target, blocked):
        if path.exists():
            raise ValueError(f"STOP: will not overwrite {path}")
    queue_bytes = queue_path.read_bytes()
    queue, queue_sha = json.loads(queue_bytes), hashlib.sha256(queue_bytes).hexdigest()
    export = json.loads(export_path.read_text(encoding="utf-8"))
    decisions, problems, missing = validate_export(queue, queue_sha, export)
    v1_before = sha256(labels_v1)
    v1 = json.loads(labels_v1.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    if problems or missing:
        report = {"status": "BLOCKED", "problems": problems, "required_without_valid_decision": missing,
                  "labels_v2_written": False, "inputs": {"labels_v1_sha256": v1_before, "queue_sha256": queue_sha,
                                                         "export_sha256": sha256(export_path)}}
        blocked.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    by_id = {item["id"]: item for item in queue["items"]}
    changes, labels = [], []
    for row in v1["labels"]:
        decision = decisions.get(row["id"])
        if decision is None:
            labels.append({**row, "review": {**row["review"], "v2_provenance": "v1_unchanged"}})
            continue
        final, blind = decision["final"], decision["blind"]
        review = {
            "status": "verified" if final["status"] == "verified" else "uncertain",
            "region": "stamp_artifact" if final["status"] == "not_text" else final["region"],
            "reference": final.get("text") if final["status"] == "verified" else None,
            "verified_by_human": final["status"] == "verified",
            "original_ocr_unchanged": True,
            "v2_provenance": "blind_recheck_v2",
            "blind_transcription": blind.get("text"), "blind_status": blind["status"],
            "blind_locked_at": blind["locked_at"], "revealed_at": decision["revealed_at"],
            "decided_at": final["decided_at"], "reviewer": export["reviewer"],
            "post_reveal_change_reason": final.get("note") or None,
            "v1_review": row["review"],
            "evidence_shown_after_lock": by_id[row["id"]]["reveal"],
        }
        before = tuple(row["review"].get(key) for key in ("reference", "status", "region"))
        if (review["reference"], review["status"], review["region"]) != before:
            changes.append({"id": row["id"], "v1": before[0], "v2": review["reference"],
                            "v1_status": before[1], "v2_status": review["status"],
                            "v1_region": before[2], "v2_region": review["region"]})
        labels.append({**row, "review": review})
    if sha256(labels_v1) != v1_before:
        raise RuntimeError("STOP: labels v1 changed while building v2")
    statuses = [label["review"]["status"] for label in labels]
    result = {
        **{k: v for k, v in v1.items() if k not in ("labels", "summary", "schema", "generated_at")},
        "schema": LABELS_V2_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "derived_from": {"labels_v1_sha256": v1_before, "queue_sha256": queue_sha,
                         "export_sha256": sha256(export_path), "reviewer": export["reviewer"]},
        "summary": {"total": len(labels), "verified": statuses.count("verified"),
                    "uncertain": statuses.count("uncertain"), "rechecked": len(decisions), "changed": len(changes)},
        "changes": changes,
        "labels": labels,
    }
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "WRITTEN", "path": str(target), **result["summary"]}


# ------------------------------------------------------- training quarantine

QUARANTINE_COLUMNS = ("id", "split", "reason", "status", "opened", "note")
DATASET_MANIFESTS = Path(__file__).resolve().parents[3] / "datasets" / "vietnamese_recognition" / "manifests"


def read_plain_tsv(path: Path) -> tuple[list[str], list[dict]]:
    """Fields hold no tab and follow no quoting rule (as datasets' dataset_common.read_table)."""
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def write_plain_tsv(path: Path, columns: tuple[str, ...], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(columns), delimiter="\t", quoting=csv.QUOTE_NONE,
                                quotechar=None, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def quarantine_review(queue_path: Path, export_path: Path, quarantine_path: Path, manifest_paths: list[Path],
                      output_dir: Path, *, apply: bool = False) -> dict:
    """Release a quarantined training label ONLY when a valid blind re-check verified it exactly as it stands.

    A verified reading that differs from the current label keeps the line quarantined and is reported
    as a correction for the user to make; uncertain, not-text and undecided lines stay quarantined.
    Writes quarantine_review.json and label_quarantine.proposed.tsv into a new output_dir. Only with
    ``apply`` is the quarantine file rewritten, after its previous version is copied to output_dir.
    Labels and manifests are never edited.
    """
    if output_dir.exists():
        raise ValueError(f"STOP: will not overwrite {output_dir}")
    queue_bytes = queue_path.read_bytes()
    queue, queue_sha = json.loads(queue_bytes), hashlib.sha256(queue_bytes).hexdigest()
    export = json.loads(export_path.read_text(encoding="utf-8"))
    decisions, problems, missing = validate_export(queue, queue_sha, export)
    columns, rows = read_plain_tsv(quarantine_path)
    if tuple(columns) != QUARANTINE_COLUMNS:
        raise ValueError(f"STOP: unexpected quarantine columns {columns}")
    labels = {}
    for path in manifest_paths:
        labels.update({row["id"]: row["text"] for row in read_plain_tsv(path)[1]})
    for item in queue["items"]:
        if labels.get(item["id"]) != item["reveal"]["v1_label"]:
            raise ValueError(f"STOP: the training label of {item['id']} changed since the queue was built")
    output_dir.mkdir(parents=True)
    inputs = {"queue_sha256": queue_sha, "export_sha256": sha256(export_path), "quarantine_sha256": sha256(quarantine_path)}
    if problems:
        report = {"status": "BLOCKED", "problems": problems, "released": [], "quarantine_changed": False, "inputs": inputs}
        (output_dir / "quarantine_review.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    open_ids = {row["id"] for row in rows if row["status"] == "open"}
    outcome = []
    for item in queue["items"]:
        current, decision = labels[item["id"]], decisions.get(item["id"])
        final = (decision or {}).get("final", {})
        if item["id"] not in open_ids:
            verdict, why = "not_open", "no open quarantine row"
        elif decision is None:
            verdict, why = "keep_open", "no valid blind decision"
        elif final["status"] == "verified" and nfc(final["text"]) == nfc(current):
            verdict, why = "release", "blind re-check verified the label as it stands"
        elif final["status"] == "verified":
            verdict, why = "keep_open_correction_proposed", "the verified reading differs from the label; correct the label first"
        else:
            verdict, why = "keep_open", f"final status {final['status']}"
        outcome.append({"id": item["id"], "verdict": verdict, "reason": why, "current_label": current,
                        "verified_text": final.get("text") if final.get("status") == "verified" else None,
                        "blind_text": (decision or {}).get("blind", {}).get("text")})
    released = {o["id"] for o in outcome if o["verdict"] == "release"}
    day = datetime.now(timezone.utc).date().isoformat()
    note = f"released {day}: blind re-check verified as is by {export['reviewer']} (export {inputs['export_sha256'][:12]})"
    proposed = [{**row, "status": "resolved", "note": note} if row["id"] in released else row for row in rows]
    write_plain_tsv(output_dir / "label_quarantine.proposed.tsv", QUARANTINE_COLUMNS, proposed)
    report = {"status": "REVIEWED", "reviewer": export["reviewer"], "released": sorted(released),
              "still_open": sorted(open_ids - released),
              "corrections_proposed": [o for o in outcome if o["verdict"] == "keep_open_correction_proposed"],
              "required_without_valid_decision": missing, "items": outcome, "quarantine_changed": False, "inputs": inputs}
    if apply and released:
        (output_dir / "label_quarantine.before.tsv").write_bytes(quarantine_path.read_bytes())
        write_plain_tsv(quarantine_path, QUARANTINE_COLUMNS, proposed)
        report.update({"quarantine_changed": True, "quarantine_sha256_after": sha256(quarantine_path)})
    (output_dir / "quarantine_review.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


# --------------------------------------------------------------- text layer

def textlayer_report(v1_dir: Path, labels_path: Path) -> dict:
    """Per line: OCR vs label, OCR vs PDF text layer, label vs PDF text layer."""
    integrity = json.loads((v1_dir / "label_integrity_report.json").read_text(encoding="utf-8"))
    labels = {r["id"]: r for r in json.loads(labels_path.read_text(encoding="utf-8"))["labels"]}
    rows = []
    for sample in integrity["samples"]:
        if not sample.get("text_layer"):
            continue
        label = labels[sample["id"]]
        ocr, reference, layer = nfc(label["ocr_original"]), label["review"].get("reference"), sample["text_layer"]["text_layer"]
        if not isinstance(reference, str):
            continue
        reference = nfc(reference)
        rows.append({
            "id": sample["id"], "document": sample["document"], "page": sample["page"],
            "line_index": sample["line_index"], "sample_group": sample["sample_group"],
            "ocr": ocr, "label_v1": reference, "pdf_text_layer": layer,
            "ocr_vs_label_char_errors": distance(reference, ocr), "label_chars": len(reference),
            "ocr_vs_pdf_char_errors": distance(layer, ocr), "pdf_chars": len(layer),
            "label_vs_pdf_char_distance": distance(layer, reference),
            "ocr_vs_label_word_errors": distance(reference.split(), ocr.split()),
            "ocr_vs_pdf_word_errors": distance(layer.split(), ocr.split()),
        })
    for row in rows:
        row["ocr_vs_label_cer"] = row["ocr_vs_label_char_errors"] / row["label_chars"]
        row["ocr_vs_pdf_cer"] = row["ocr_vs_pdf_char_errors"] / row["pdf_chars"]
        row["delta_char_errors_pdf_minus_label"] = row["ocr_vs_pdf_char_errors"] - row["ocr_vs_label_char_errors"]
    return {
        "schema": "vietdoc_textlayer_17_v1",
        "lines": len(rows),
        "normalization": "Unicode NFC; whitespace runs in the text layer collapsed; micro Levenshtein",
        "ocr_vs_label": metrics([(r["label_v1"], r["ocr"]) for r in rows]) if rows else None,
        "ocr_vs_pdf_text": metrics([(r["pdf_text_layer"], r["ocr"]) for r in rows]) if rows else None,
        "label_disagrees_with_pdf": [r["id"] for r in rows if r["label_vs_pdf_char_distance"]],
        "rows": rows,
    }


# ------------------------------------------------------------------ CLI

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    queue = commands.add_parser("queue", help="blind re-check queue for the 40-line pack")
    queue.add_argument("--pack-dir", type=Path, required=True)
    queue.add_argument("--labels", type=Path, required=True)
    queue.add_argument("--pdf-dir", type=Path, required=True)
    queue.add_argument("--v1-dir", type=Path, required=True)
    queue.add_argument("--output-dir", type=Path, required=True)
    train = commands.add_parser("train-queue", help="blind re-check queue for quarantined training labels")
    train.add_argument("--audit-csv", type=Path, required=True)
    train.add_argument("--dataset-dir", type=Path, required=True)
    train.add_argument("--output-dir", type=Path, required=True)
    build = commands.add_parser("labels-v2", help="validate a reviewer export; write labels v2 or BLOCKED")
    build.add_argument("--labels-v1", type=Path, required=True)
    build.add_argument("--queue", type=Path, required=True)
    build.add_argument("--export", type=Path, required=True)
    build.add_argument("--output-dir", type=Path, required=True)
    review = commands.add_parser("quarantine-review",
                                 help="release only quarantined training labels a blind re-check verified as is")
    review.add_argument("--queue", type=Path, required=True)
    review.add_argument("--export", type=Path, required=True)
    review.add_argument("--quarantine", type=Path, default=DATASET_MANIFESTS / "label_quarantine.tsv")
    review.add_argument("--manifests", type=Path, nargs="+",
                        default=[DATASET_MANIFESTS / "real_train.tsv", DATASET_MANIFESTS / "real_val.tsv"])
    review.add_argument("--output-dir", type=Path, required=True)
    review.add_argument("--apply", action="store_true", help="rewrite the quarantine file (previous copy kept)")
    layer = commands.add_parser("textlayer", help="OCR vs label vs PDF text on lines with a text layer")
    layer.add_argument("--v1-dir", type=Path, required=True)
    layer.add_argument("--labels", type=Path, required=True)
    layer.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "queue":
        result = write_queue(eval_items(args.pack_dir, args.labels, args.pdf_dir, args.v1_dir), args.output_dir,
                             "vietdoc40_recheck_v2", "VietDoc 40 dòng — gõ mù nhãn v2")
    elif args.command == "train-queue":
        with args.audit_csv.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        result = write_queue(train_items(rows, args.dataset_dir), args.output_dir,
                             "train_val_label_recheck_v1", "Nhãn train/val bị cách ly — gõ mù")
    elif args.command == "labels-v2":
        result = build_labels_v2(args.labels_v1, args.queue, args.export, args.output_dir)
    elif args.command == "quarantine-review":
        result = quarantine_review(args.queue, args.export, args.quarantine, args.manifests, args.output_dir,
                                   apply=args.apply)
    else:
        if args.output.exists():
            raise ValueError(f"STOP: will not overwrite {args.output}")
        result = textlayer_report(args.v1_dir, args.labels)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result = {k: result[k] for k in ("lines", "ocr_vs_label", "ocr_vs_pdf_text", "label_disagrees_with_pdf")}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


REVIEW_PAGE = r"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gõ mù nhãn v2</title>
<style>
:root{--bg:#f4f5f8;--card:#fff;--ink:#1d2433;--muted:#5b6478;--line:#d9dde6;--accent:#1f5fbf;--warn:#b42318;--ok:#067647}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,Segoe UI,sans-serif}
header{position:sticky;top:0;background:var(--card);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center;z-index:2}
header h1{font-size:17px;margin:0 12px 0 0}main{display:grid;grid-template-columns:260px 1fr;gap:16px;padding:16px;max-width:1500px;margin:auto}
nav{background:var(--card);border:1px solid var(--line);border-radius:8px;max-height:80vh;overflow:auto}
nav button{display:block;width:100%;text-align:left;border:0;border-bottom:1px solid var(--line);background:none;padding:7px 10px;font:13px system-ui;cursor:pointer}
nav button.current{background:#e8efff}nav .req{color:var(--warn);font-weight:600}
section{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px}
.view{overflow:auto;border:1px solid var(--line);background:#fff;padding:6px;margin:8px 0}.view img{image-rendering:auto;transform-origin:0 0}
textarea{width:100%;min-height:62px;font:18px/1.4 "Times New Roman",serif;padding:8px}
button.act{padding:8px 14px;margin:6px 6px 0 0;border:1px solid var(--line);border-radius:6px;background:#fff;cursor:pointer}
button.primary{background:var(--accent);color:#fff;border-color:var(--accent)}button:disabled{opacity:.45;cursor:not-allowed}
table{border-collapse:collapse;width:100%;margin-top:8px}td,th{border:1px solid var(--line);padding:6px 8px;vertical-align:top;text-align:left}
td.txt{font:17px/1.4 "Times New Roman",serif}del{background:#fde2e1;text-decoration:none}ins{background:#d9f2e3;text-decoration:none}
.note{color:var(--muted);font-size:13px}.banner{padding:8px 10px;border-radius:6px;background:#fff6e5;border:1px solid #f2c46d;margin:8px 0}
@media (max-width:900px){main{grid-template-columns:1fr}nav{max-height:none}}
</style></head><body>
<header><h1 id="title"></h1>
<label>Người review: <input id="reviewer" size="18"></label>
<span id="progress"></span>
<button class="act" id="save">Tải JSON kết quả</button>
<label class="act" style="cursor:pointer">Mở JSON tiến độ<input id="load" type="file" accept=".json" hidden></label>
</header>
<main><nav id="list"></nav><section id="item"></section></main>
<script>
const CFG = __CONFIG__;
const state = {reviewer: "", items: {}};
let current = 0;
const now = () => new Date().toISOString();
const unseal = s => JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(s), c => c.charCodeAt(0))));
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function entry(id){ return state.items[id] ??= {image_sha256: CFG.items.find(i => i.id === id).image_sha256, blind: {}, final: {}}; }
function diff(a, b){ // character LCS diff of b against a, for display only
  a = [...(a ?? "")]; b = [...(b ?? "")]; const n = a.length, m = b.length;
  const t = Array.from({length: n + 1}, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) t[i][j] = a[i] === b[j] ? t[i+1][j+1] + 1 : Math.max(t[i+1][j], t[i][j+1]);
  let i = 0, j = 0, out = "";
  while (i < n && j < m) { if (a[i] === b[j]) { out += esc(a[i]); i++; j++; } else if (t[i+1][j] >= t[i][j+1]) { out += "<del>" + esc(a[i++]) + "</del>"; } else { out += "<ins>" + esc(b[j++]) + "</ins>"; } }
  while (i < n) out += "<del>" + esc(a[i++]) + "</del>"; while (j < m) out += "<ins>" + esc(b[j++]) + "</ins>";
  return out;
}
function done(id){ const e = state.items[id]; return e && e.blind.locked_at && e.final.decided_at; }
function renderList(){
  const list = document.getElementById("list"); list.innerHTML = "";
  CFG.items.forEach((item, k) => {
    const b = document.createElement("button"); b.className = k === current ? "current" : "";
    b.innerHTML = (done(item.id) ? "✔ " : (state.items[item.id]?.blind.locked_at ? "◐ " : "○ ")) +
      (item.required ? '<span class="req">[bắt buộc]</span> ' : "") + esc(item.where);
    b.onclick = () => { current = k; render(); }; list.appendChild(b);
  });
  const req = CFG.items.filter(i => i.required), ok = req.filter(i => done(i.id)).length;
  document.getElementById("progress").textContent = `Bắt buộc: ${ok}/${req.length} · Tổng đã xong: ${CFG.items.filter(i => done(i.id)).length}/${CFG.items.length}`;
}
function render(){
  renderList(); const item = CFG.items[current], e = entry(item.id), box = document.getElementById("item");
  const locked = !!e.blind.locked_at;
  box.innerHTML = `<h2 style="margin:0 0 4px;font-size:16px">${esc(item.where)} ${item.required ? '<span class="req" style="color:var(--warn)">— bắt buộc</span>' : '— tùy chọn (lượt gõ mù thứ hai)'}</h2>
  <p class="note">Gõ đúng nguyên văn dòng có <b style="color:var(--warn)">vạch đỏ</b> bên trái, kể cả dấu thanh, dấu câu, chữ hoa. Không đoán chữ bị che; nếu không đọc chắc chắn, chọn "Không đọc được".</p>
  <div><button class="act" data-z="1">1×</button><button class="act" data-z="2">2×</button><button class="act" data-z="3">3×</button></div>
  <div class="view"><img id="img" src="${item.image}" alt="ảnh dòng"></div>
  <div id="blind"></div><div id="reveal"></div>`;
  box.querySelectorAll("[data-z]").forEach(b => b.onclick = () => { const img = document.getElementById("img"); img.style.transform = `scale(${b.dataset.z})`; img.parentElement.style.height = (img.naturalHeight * b.dataset.z + 14) + "px"; });
  const blind = document.getElementById("blind");
  blind.innerHTML = `<textarea id="t" ${locked ? "readonly" : ""} placeholder="Gõ lại dòng trong ảnh…">${esc(e.blind.text ?? "")}</textarea>
   <label>Loại vùng: <select id="r" ${locked ? "disabled" : ""}>${CFG.regions.map(r => `<option ${r === (e.blind.region ?? "printed_text") ? "selected" : ""}>${r}</option>`).join("")}</select></label><br>
   <button class="act primary" id="lock" ${locked ? "disabled" : ""}>Khóa bản gõ mù</button>
   <button class="act" id="unr" ${locked ? "disabled" : ""}>Không đọc được</button>
   <button class="act" id="nt" ${locked ? "disabled" : ""}>Không phải chữ</button>
   ${locked ? `<p class="note">Đã khóa lúc ${esc(e.blind.locked_at)} (${esc(e.blind.status)}). Bản gõ mù không sửa được nữa.</p>` : ""}`;
  const lock = status => { const text = document.getElementById("t").value.normalize("NFC").replace(/\s+/g, " ").trim();
    if (status === "typed" && !text) { alert("Chưa gõ gì. Nếu không đọc được, chọn 'Không đọc được'."); return; }
    Object.assign(e.blind, {text: status === "typed" ? text : "", region: document.getElementById("r").value, status, locked_at: now()});
    e.revealed_at = now(); render(); };
  if (!locked) { document.getElementById("lock").onclick = () => lock("typed"); document.getElementById("unr").onclick = () => lock("unreadable"); document.getElementById("nt").onclick = () => lock("not_text"); }
  if (locked) renderReveal(item, e);
}
function renderReveal(item, e){
  const r = unseal(item.sealed), blindTyped = e.blind.status === "typed", f = e.final;
  const rows = [["Bản gõ mù (đã khóa)", e.blind.text, false], ["Nhãn v1", r.v1_label, true], ["OCR gốc", r.ocr_original, true], ["Lớp chữ PDF", r.pdf_text_layer, true]];
  document.getElementById("reveal").innerHTML = `<div class="banner">Chỉ hiện sau khi khóa. Nhìn lại ẢNH trước khi quyết định; đừng chọn theo OCR.</div>
  <table><tr><th>Nguồn</th><th>Nội dung (tô màu: khác với bản gõ mù)</th></tr>${rows.filter(x => x[1] !== null && x[1] !== undefined).map(x => `<tr><td>${x[0]}</td><td class="txt">${x[2] ? diff(e.blind.text, x[1]) : esc(x[1])}</td></tr>`).join("")}</table>
  ${r.evidence ? `<p class="note">Bằng chứng v1: ${esc(r.evidence)}</p>` : ""}
  <fieldset style="margin-top:10px"><legend>Quyết định cuối</legend>
   ${blindTyped ? `<label><input type="radio" name="d" value="keep" ${f.choice === "keep" ? "checked" : ""}> Giữ bản gõ mù</label><br>
   <label><input type="radio" name="d" value="edit" ${f.choice === "edit" ? "checked" : ""}> Sửa sau khi nhìn ảnh lại (bắt buộc ghi lý do)</label><br>` : `<p class="note">Lượt gõ mù không đọc được: chỉ được kết luận uncertain hoặc không phải chữ.</p>`}
   <label><input type="radio" name="d" value="uncertain" ${f.choice === "uncertain" ? "checked" : ""}> Không chắc (uncertain)</label><br>
   <label><input type="radio" name="d" value="not_text" ${f.choice === "not_text" ? "checked" : ""}> Không phải chữ (stamp_artifact)</label><br>
   <textarea id="fe" placeholder="Văn bản cuối (chỉ khi chọn Sửa)">${esc(f.choice === "edit" ? f.text : "")}</textarea>
   <input id="note" style="width:100%" placeholder="Lý do (bắt buộc nếu khác bản gõ mù)" value="${esc(f.note ?? "")}">
   <button class="act primary" id="decide">Xác nhận quyết định</button>
   ${f.decided_at ? `<p class="note">Đã quyết định lúc ${esc(f.decided_at)}: ${esc(f.status)}</p>` : ""}
  </fieldset>`;
  document.getElementById("decide").onclick = () => {
    const choice = document.querySelector('input[name="d"]:checked')?.value; if (!choice) { alert("Chọn một quyết định."); return; }
    const note = document.getElementById("note").value.trim(); let text = null, status = choice === "not_text" ? "not_text" : (choice === "uncertain" ? "uncertain" : "verified");
    if (choice === "keep") text = e.blind.text;
    if (choice === "edit") { text = document.getElementById("fe").value.normalize("NFC").replace(/\s+/g, " ").trim(); if (!text || !note) { alert("Sửa cần văn bản và lý do."); return; } }
    if (status === "verified" && !blindTyped) { alert("Không thể verified khi lượt gõ mù không đọc được."); return; }
    Object.assign(e.final, {choice, status, text, region: status === "not_text" ? "stamp_artifact" : (status === "uncertain" ? "uncertain" : e.blind.region), note, decided_at: now()});
    if (current < CFG.items.length - 1) current++; render(); };
}
document.getElementById("title").textContent = CFG.title;
document.getElementById("reviewer").oninput = ev => state.reviewer = ev.target.value.trim();
document.getElementById("save").onclick = () => {
  if (!state.reviewer) { alert("Nhập tên người review trước khi tải JSON."); return; }
  const data = {schema: CFG.export_schema, queue_id: CFG.queue_id, queue_sha256: CFG.queue_sha256, reviewer: state.reviewer, exported_at: now(), items: state.items};
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: "application/json"}));
  a.download = `${CFG.queue_id}_blind_review_export.json`; a.click(); };
document.getElementById("load").onchange = ev => { const file = ev.target.files[0]; if (!file) return; file.text().then(t => { const d = JSON.parse(t);
  if (d.queue_id !== CFG.queue_id || d.queue_sha256 !== CFG.queue_sha256) { alert("JSON này thuộc hàng đợi khác."); return; }
  state.items = d.items || {}; state.reviewer = d.reviewer || ""; document.getElementById("reviewer").value = state.reviewer; render(); }); };
render();
</script></body></html>
"""


if __name__ == "__main__":
    raise SystemExit(main())

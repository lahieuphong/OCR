"""Correction addendum for a locked blind-review export: re-check a few lines from the image only.

Run from repo root (Windows CMD):
  .venv-demo\\Scripts\\python.exe -m demo.local_pdf_ocr.quality.gt_v2_addendum check ^
    --queue <gt_v2>\\vietdoc40_recheck_v2.queue.json --export <...>\\vietdoc40_recheck_v2_blind_review_export.json ^
    --output-dir <new_dir>
  ... gt_v2_addendum page --queue <...> --review-html <gt_v2>\\vietdoc40_recheck_v2.review.html --export <...> ^
    --pack-dir vietdoc_5pdf_quality_review_40 --pdf-dir "<SAMPLES_DIR>" ^
    --ids <id> [<id> ...] --output-dir <new_dir>\\addendum
  ... gt_v2_addendum labels-v2 --labels-v1 <...> --queue <...> --export <...> ^
    --page <new_dir>\\addendum\\addendum_page.json --addendum <...>_correction_addendum_v1.json --output-dir <new_dir>\\labels_v2

The export stays the immutable record of the blind review; nothing here edits it.
``check`` validates it (schema, queue id and SHA-256, every item locked and decided)
and copies it byte for byte as evidence. ``page`` writes an offline page for the
chosen lines only: the line image the reviewer saw (hash-checked against the queue),
a sharper render of the same PDF region, and the reviewer's own blind and final
entries -- never OCR, the v1 label or the PDF text layer. The page exports an
addendum that names the export, the queue and the page by SHA-256. ``labels-v2``
builds labels v2 only when the export and the addendum are both valid. Lines outside
the addendum keep their export entries field for field; a re-checked line keeps its
blind entry and its superseded final decision and carries the correction with its
reason, time and reviewer. labels v2 is built by gt_v2.build_labels_v2 itself.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import math
import shutil
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import gt_v2
from .benchmark import nfc

ADDENDUM_SCHEMA = "vietdoc_blind_review_correction_addendum_v1"
PAGE_SCHEMA = "vietdoc_blind_review_correction_page_v1"
ACTIONS = ("confirm", "correct", "uncertain")
SHARP_ZOOM = 4.0
CORRECTION_REGIONS = tuple(r for r in gt_v2.REGIONS if r != "uncertain")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read(path: Path) -> tuple[bytes, dict, str]:
    data = Path(path).read_bytes()
    return data, json.loads(data), sha256_bytes(data)


def stamp(value) -> datetime | None:
    """An ISO-8601 time with a zone (browser toISOString or Python isoformat), else None."""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


# ----------------------------------------------------------- export check

def check_export(queue_path: Path, export_path: Path) -> dict:
    """Schema, queue id and SHA-256, item coverage and decision states of a blind-review export."""
    _, queue, queue_sha = read(queue_path)
    export_bytes, export, export_sha = read(export_path)
    decisions, problems, missing = gt_v2.validate_export(queue, queue_sha, export)
    queue_ids = [item["id"] for item in queue["items"]]
    entries = export.get("items") or {}
    return {
        "export_file": str(export_path), "export_sha256": export_sha, "export_bytes": len(export_bytes),
        "schema_ok": export.get("schema") == gt_v2.EXPORT_SCHEMA, "queue_id_ok": export.get("queue_id") == queue["queue_id"],
        "queue_sha256_ok": export.get("queue_sha256") == queue_sha, "queue_sha256": queue_sha,
        "reviewer": export.get("reviewer"), "exported_at": export.get("exported_at"),
        "queue_items": len(queue_ids), "export_items": len(entries),
        "missing_from_export": sorted(set(queue_ids) - set(entries)), "not_in_queue": sorted(set(entries) - set(queue_ids)),
        "locked": sum(bool((e.get("blind") or {}).get("locked_at")) for e in entries.values()),
        "decided": sum(bool((e.get("final") or {}).get("decided_at")) for e in entries.values()),
        "valid_decisions": len(decisions), "required": sum(item["required"] for item in queue["items"]),
        "required_without_valid_decision": missing, "problems": problems,
        "blind_status": dict(Counter((e.get("blind") or {}).get("status") for e in entries.values())),
        "final_status": dict(Counter((e.get("final") or {}).get("status") for e in entries.values())),
        "final_differs_from_blind": sorted(i for i, d in decisions.items() if d["final"].get("status") == "verified"
                                           and nfc(d["final"].get("text") or "") != nfc(d["blind"].get("text") or "")),
        "complete": not problems and not missing and len(decisions) == len(queue_ids),
        "valid": not problems and not missing,
    }


def keep_evidence(export_path: Path, output_dir: Path) -> dict:
    """A byte-identical copy of the export plus its SHA-256; the original file is only read."""
    target = output_dir / "evidence" / Path(export_path).name
    if target.exists():
        raise ValueError(f"STOP: will not overwrite {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    original = Path(export_path).read_bytes()
    target.write_bytes(original)
    digest = sha256_bytes(original)
    if sha256_bytes(target.read_bytes()) != digest:
        raise RuntimeError("STOP: the evidence copy differs from the export")
    (target.parent / (target.name + ".sha256")).write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    return {"evidence": str(target), "sha256": digest}


# ------------------------------------------------------------------- page

def review_images(review_html: Path, queue: dict, queue_sha: str) -> dict[str, bytes]:
    """The exact line images of the original review page, checked against the queue hashes."""
    html = Path(review_html).read_text(encoding="utf-8")
    start = html.index("const CFG = ") + len("const CFG = ")
    config, _ = json.JSONDecoder().raw_decode(html, start)
    if config.get("queue_id") != queue["queue_id"] or config.get("queue_sha256") != queue_sha:
        raise ValueError("STOP: the review page belongs to another queue")
    expected = {item["id"]: item["image_sha256"] for item in queue["items"]}
    images = {}
    for item in config["items"]:
        image = base64.b64decode(item["image"].split(",", 1)[1])
        if sha256_bytes(image) != expected.get(item["id"]):
            raise ValueError(f"STOP: the review page image of {item['id']} differs from the queue")
        images[item["id"]] = image
    return images


def sharp_view(pdf_path: Path, page_number: int, polygon: list, zoom: float = SHARP_ZOOM) -> bytes:
    """The region of the review image rendered again from the PDF at a higher zoom (rendering only, no OCR)."""
    import fitz
    from PIL import Image

    with fitz.open(pdf_path) as pdf:
        page = pdf[page_number - 1]
        base = min(2.0, math.sqrt(12_000_000 / (page.rect.width * page.rect.height)))  # zoom of the polygon raster
        xs, ys = [p[0] / base for p in polygon], [p[1] / base for p in polygon]
        dx, dy = gt_v2.CONTEXT_PX[0] / base, gt_v2.CONTEXT_PX[1] / base
        clip = fitz.Rect(max(0, min(xs) - dx), max(0, min(ys) - dy),
                         min(page.rect.width, max(xs) + dx), min(page.rect.height, max(ys) + dy))
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, colorspace=fitz.csRGB, alpha=False)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    top, bottom = int((min(ys) - clip.y0) * zoom), int(math.ceil((max(ys) - clip.y0) * zoom))
    return gt_v2.png_bytes(gt_v2.with_marker(image, top, bottom))


def write_page(queue_path: Path, review_html: Path, export_path: Path, pack_dir: Path, pdf_dir: Path,
               ids: list[str], output_dir: Path) -> dict:
    check = check_export(queue_path, export_path)
    if not check["valid"]:
        raise ValueError(f"STOP: the export is not valid: {check['problems'] or check['required_without_valid_decision']}")
    _, queue, queue_sha = read(queue_path)
    _, export, export_sha = read(export_path)
    by_queue = {item["id"]: item for item in queue["items"]}
    unknown = [i for i in ids if i not in by_queue or i not in (export.get("items") or {})]
    if unknown or len(set(ids)) != len(ids) or not ids:
        raise ValueError(f"STOP: ids must be distinct items of the queue and the export: {unknown or ids}")
    page_id = f"{queue['queue_id']}_correction_addendum_v1"
    targets = (output_dir / "addendum_page.json", output_dir / f"{page_id}.review.html")
    if any(t.exists() for t in targets):
        raise ValueError("STOP: will not overwrite an addendum page")
    images = review_images(review_html, queue, queue_sha)
    samples = {s["id"]: s for s in json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))["samples"]}
    items, pictures = [], {}
    for identifier in ids:
        sample, entry = samples[identifier], export["items"][identifier]
        pdf = pdf_dir / sample["document"]
        if gt_v2.sha256(pdf) != sample["pdf_sha256"]:
            raise ValueError(f"STOP: PDF hash differs: {pdf}")
        sharp = sharp_view(pdf, sample["page"], sample["polygon"])
        pictures[identifier] = (images[identifier], sharp)
        items.append({"id": identifier, "where": f"{sample['document']} · tr.{sample['page']} · dòng {sample['line_index']}",
                      "document": sample["document"], "page": sample["page"], "line_index": sample["line_index"],
                      "image_sha256": by_queue[identifier]["image_sha256"], "sharp_sha256": sha256_bytes(sharp),
                      "sharp_zoom": SHARP_ZOOM, "previous_blind": entry.get("blind"), "previous_final": entry.get("final"),
                      "previous_revealed_at": entry.get("revealed_at")})
    page = {"schema": PAGE_SCHEMA, "page_id": page_id, "created_at": now(), "title": "VietDoc GT v2 — xác minh lại "
            f"{len(items)} dòng (bổ sung, không gõ lại)", "queue_id": queue["queue_id"], "queue_sha256": queue_sha,
            "base_export_sha256": export_sha, "base_export_file": Path(export_path).name,
            "base_reviewer": export.get("reviewer"), "base_exported_at": export.get("exported_at"),
            "regions": list(CORRECTION_REGIONS), "addendum_schema": ADDENDUM_SCHEMA, "items": items,
            "shown": "line images and the reviewer's own entries only (no OCR, no v1 label, no PDF text layer)"}
    output_dir.mkdir(parents=True, exist_ok=True)
    page_bytes = json.dumps(page, ensure_ascii=False, indent=1).encode("utf-8")
    targets[0].write_bytes(page_bytes)
    config = {**page, "page_sha256": sha256_bytes(page_bytes),
              "items": [{**item, "image": "data:image/png;base64," + base64.b64encode(pictures[item["id"]][0]).decode(),
                         "sharp": "data:image/png;base64," + base64.b64encode(pictures[item["id"]][1]).decode()}
                        for item in items]}
    targets[1].write_text(ADDENDUM_PAGE.replace("__CONFIG__", json.dumps(config, ensure_ascii=False)), encoding="utf-8")
    return {"page": str(targets[0]), "html": str(targets[1]), "page_sha256": config["page_sha256"], "items": len(items)}


# ------------------------------------------------------------ validation

def validate_addendum(queue: dict, queue_sha: str, export: dict, export_sha: str, page: dict, page_sha: str,
                      addendum: dict) -> tuple[dict, list[str]]:
    """Valid corrections by id, or the problems that block every one of them."""
    problems = []
    if addendum.get("schema") != ADDENDUM_SCHEMA:
        problems.append("addendum schema is not " + ADDENDUM_SCHEMA)
    expected = {"queue_id": queue["queue_id"], "queue_sha256": queue_sha, "base_export_sha256": export_sha,
                "page_sha256": page_sha, "page_id": page.get("page_id")}
    problems += [f"{key} does not match" for key, value in expected.items() if addendum.get(key) != value]
    if page.get("base_export_sha256") != export_sha or page.get("queue_sha256") != queue_sha:
        problems.append("the page was built from another export or queue")
    if not str(addendum.get("reviewer", "")).strip():
        problems.append("reviewer ID missing")
    entries, on_page = addendum.get("items") or {}, {item["id"]: item for item in page.get("items", [])}
    problems += [f"{i}: not on the addendum page" for i in sorted(set(entries) - set(on_page))]
    problems += [f"{i}: no decision in the addendum" for i in sorted(set(on_page) - set(entries))]
    by_queue = {item["id"]: item for item in queue["items"]}
    exported_at = stamp(export.get("exported_at"))
    corrections = {}
    for identifier, entry in entries.items():
        if identifier not in on_page:
            continue
        where, original = f"{identifier}:", export["items"][identifier]
        blind, final = original.get("blind") or {}, original.get("final") or {}
        action, reason, decided = entry.get("action"), str(entry.get("reason") or "").strip(), stamp(entry.get("decided_at"))
        final_at = stamp(final.get("decided_at"))
        before = len(problems)
        if entry.get("image_sha256") != by_queue[identifier]["image_sha256"]:
            problems.append(f"{where} image differs from the queue")
        if entry.get("previous_blind") != original.get("blind") or entry.get("previous_final") != original.get("final"):
            problems.append(f"{where} the addendum was made against other export entries")
        if action not in ACTIONS:
            problems.append(f"{where} unknown action {action!r}")
        if not reason:
            problems.append(f"{where} a written reason is required")
        if not decided or not exported_at or decided <= exported_at or (final_at and decided < final_at):
            problems.append(f"{where} the correction must be dated after the export")
        if action == "correct":
            text = entry.get("text")
            if not isinstance(text, str) or not text.strip() or text != text.strip() or "\n" in text or text != nfc(text):
                problems.append(f"{where} corrected text must be one non-empty NFC line without outer spaces")
            elif final.get("status") == "verified" and nfc(text) == nfc(final.get("text") or ""):
                problems.append(f"{where} corrected text equals the final decision; use confirm")
            if blind.get("status") != "typed":
                problems.append(f"{where} a line unreadable in the blind pass cannot become verified")
            if entry.get("region") not in CORRECTION_REGIONS:
                problems.append(f"{where} unknown region for a corrected line")
        elif action == "uncertain" and entry.get("text"):
            problems.append(f"{where} uncertain must not carry a text")
        if len(problems) == before:
            corrections[identifier] = entry
    return ({} if problems else corrections), problems


def effective_export(export: dict, corrections: dict) -> dict:
    """The export with the re-checked final decisions; every blind entry and every other item untouched."""
    result = copy.deepcopy(export)
    for identifier, entry in corrections.items():
        if entry["action"] == "confirm":
            continue  # the final decision stands; the re-check is recorded as provenance
        corrected = entry["action"] == "correct"
        result["items"][identifier]["final"] = {
            "choice": "edit" if corrected else "uncertain", "status": "verified" if corrected else "uncertain",
            "text": entry["text"] if corrected else None, "region": entry["region"] if corrected else "uncertain",
            "note": "correction addendum: " + str(entry["reason"]).strip(), "decided_at": entry["decided_at"]}
    return result


# ------------------------------------------------------------ labels v2

def build(labels_v1: Path, queue_path: Path, export_path: Path, page_path: Path, addendum_path: Path,
          output_dir: Path) -> dict:
    target, blocked = output_dir / "labels_v2.json", output_dir / "labels_v2_BLOCKED.json"
    if target.exists() or blocked.exists():
        raise ValueError(f"STOP: will not overwrite {output_dir}")
    v1_before, export_before = gt_v2.sha256(labels_v1), gt_v2.sha256(export_path)
    _, queue, queue_sha = read(queue_path)
    _, export, export_sha = read(export_path)
    _, page, page_sha = read(page_path)
    _, addendum, addendum_sha = read(addendum_path)
    _, export_problems, missing = gt_v2.validate_export(queue, queue_sha, export)
    corrections, problems = validate_addendum(queue, queue_sha, export, export_sha, page, page_sha, addendum)
    inputs = {"labels_v1_sha256": v1_before, "queue_sha256": queue_sha, "export_sha256": export_sha,
              "page_sha256": page_sha, "addendum_sha256": addendum_sha}
    output_dir.mkdir(parents=True, exist_ok=True)
    if export_problems or missing or problems:
        report = {"status": "BLOCKED", "labels_v2_written": False, "export_problems": export_problems,
                  "required_without_valid_decision": missing, "addendum_problems": problems, "inputs": inputs}
        blocked.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    effective = effective_export(export, corrections)
    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        (temp / "effective_export.json").write_text(json.dumps(effective, ensure_ascii=False), encoding="utf-8")
        reference = gt_v2.build_labels_v2(labels_v1, queue_path, export_path, temp / "export_only")
        built = gt_v2.build_labels_v2(labels_v1, queue_path, temp / "effective_export.json", temp / "with_addendum")
        if reference.get("status") != "WRITTEN" or built.get("status") != "WRITTEN":
            raise RuntimeError(f"STOP: labels v2 could not be built: {reference.get('status')}, {built.get('status')}")
        export_only = json.loads((temp / "export_only" / "labels_v2.json").read_text(encoding="utf-8"))
        result = json.loads((temp / "with_addendum" / "labels_v2.json").read_text(encoding="utf-8"))
    rows, plain = {r["id"]: r for r in result["labels"]}, {r["id"]: r for r in export_only["labels"]}
    untouched_entries = [i for i in export["items"] if i not in corrections]
    entry_differences = [i for i in untouched_entries if effective["items"][i] != export["items"][i]]
    row_differences = [i for i in plain if i not in corrections and rows[i] != plain[i]]
    if entry_differences or row_differences or set(rows) != set(plain):
        raise RuntimeError(f"STOP: lines outside the addendum changed: {entry_differences or row_differences}")
    for identifier, entry in corrections.items():
        review = rows[identifier]["review"]
        review["v2_provenance"] = "blind_recheck_v2+correction_addendum_v1"
        review["correction_addendum"] = {
            "action": entry["action"], "reason": str(entry["reason"]).strip(), "decided_at": entry["decided_at"],
            "opened_at": entry.get("opened_at"), "reviewer": str(addendum["reviewer"]).strip(),
            "history": entry.get("history") or [], "superseded_final": export["items"][identifier]["final"],
            "blind_entry_unchanged": (review.get("blind_transcription"), review.get("blind_status"), review.get("blind_locked_at"))
            == tuple(export["items"][identifier]["blind"].get(k) for k in ("text", "status", "locked_at")),
            "addendum_sha256": addendum_sha, "page_sha256": page_sha}
    result["generated_at"] = now()
    result["derived_from"] = {**inputs, "reviewer": export.get("reviewer"),
                              "addendum_reviewer": str(addendum["reviewer"]).strip(),
                              "note": "labels v2 = gt_v2.build_labels_v2 over the export with the addendum's final decisions"}
    actions = Counter(entry["action"] for entry in corrections.values())
    result["summary"].update({"addendum_confirmed": actions.get("confirm", 0), "addendum_corrected": actions.get("correct", 0),
                              "addendum_uncertain": actions.get("uncertain", 0)})
    if gt_v2.sha256(labels_v1) != v1_before or gt_v2.sha256(export_path) != export_before:
        raise RuntimeError("STOP: an input changed while building labels v2")
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {"status": "WRITTEN", "labels_v2": str(target), **result["summary"], "inputs": inputs,
              "lines_outside_addendum": len(untouched_entries), "export_entries_outside_addendum_identical": True,
              "labels_outside_addendum_identical_to_export_only_build": True, "corrections": sorted(corrections),
              "original_export_unchanged": gt_v2.sha256(export_path) == export_before}
    (output_dir / "labels_v2_build_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check")
    check.add_argument("--queue", type=Path, required=True)
    check.add_argument("--export", type=Path, required=True)
    check.add_argument("--output-dir", type=Path, required=True)
    page = commands.add_parser("page")
    for name in ("--queue", "--review-html", "--export", "--pack-dir", "--pdf-dir", "--output-dir"):
        page.add_argument(name, type=Path, required=True)
    page.add_argument("--ids", nargs="+", required=True)
    build_parser = commands.add_parser("labels-v2")
    for name in ("--labels-v1", "--queue", "--export", "--page", "--addendum", "--output-dir"):
        build_parser.add_argument(name, type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "check":
        report = check_export(args.queue, args.export)
        target = args.output_dir / "export_check.json"
        if target.exists():
            raise ValueError(f"STOP: will not overwrite {target}")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        report["evidence"] = keep_evidence(args.export, args.output_dir)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        result = {k: report[k] for k in ("valid", "complete", "queue_items", "export_items", "valid_decisions",
                                         "final_status", "problems", "required_without_valid_decision")}
    elif args.command == "page":
        result = write_page(args.queue, args.review_html, args.export, args.pack_dir, args.pdf_dir, args.ids, args.output_dir)
    else:
        result = build(args.labels_v1, args.queue, args.export, args.page, args.addendum, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


ADDENDUM_PAGE = r"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Xác minh lại nhãn v2</title>
<style>
:root{--bg:#f4f5f8;--card:#fff;--ink:#1d2433;--muted:#5b6478;--line:#d9dde6;--accent:#1f5fbf;--warn:#b42318;--ok:#067647}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,Segoe UI,sans-serif}
header{position:sticky;top:0;background:var(--card);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center;z-index:2}
header h1{font-size:17px;margin:0 12px 0 0}main{padding:16px;max-width:1500px;margin:auto;display:grid;gap:16px}
section{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px}
section h2{margin:0 0 4px;font-size:16px}code{font-size:13px}
.view{overflow:auto;border:1px solid var(--line);background:#fff;padding:6px;margin:6px 0 12px}.view img{transform-origin:0 0;display:block}
textarea{width:100%;min-height:58px;font:18px/1.4 "Times New Roman",serif;padding:8px}
input.reason{width:100%;padding:6px;margin-top:6px}
button.act{padding:8px 14px;margin:6px 6px 0 0;border:1px solid var(--line);border-radius:6px;background:#fff;cursor:pointer}
button.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
table{border-collapse:collapse;width:100%;margin:8px 0}td,th{border:1px solid var(--line);padding:6px 8px;vertical-align:top;text-align:left}
th{width:300px;font-weight:600}td.txt,.txt{font:17px/1.4 "Times New Roman",serif}
del{background:#fde2e1;text-decoration:none}ins{background:#d9f2e3;text-decoration:none}
.note{color:var(--muted);font-size:13px}.banner{padding:8px 10px;border-radius:6px;background:#fff6e5;border:1px solid #f2c46d;margin:8px 0}
.done{color:var(--ok);font-weight:600}.todo{color:var(--warn);font-weight:600}
</style></head><body>
<header><h1 id="title"></h1>
<label>ID người review: <input id="reviewer" size="18"></label>
<span id="progress"></span>
<button class="act primary" id="save">Tải JSON bổ sung</button>
</header>
<main>
<div class="banner">Trang này chỉ sửa bổ sung các dòng dưới đây; file export gốc giữ nguyên. Chỉ dựa vào ẢNH:
trang không hiện OCR, nhãn v1 hay lớp chữ PDF. Mỗi dòng cần một quyết định và một lý do.</div>
<div id="items"></div>
</main>
<script>
const CFG = __CONFIG__;
const PAGE_OPENED = new Date().toISOString();
const state = {reviewer: "", items: {}};
const now = () => new Date().toISOString();
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const clean = s => String(s ?? "").normalize("NFC").replace(/\s+/g, " ").trim();
function diff(a, b){ // character LCS diff of b against a, for display only
  a = [...(a ?? "")]; b = [...(b ?? "")]; const n = a.length, m = b.length;
  const t = Array.from({length: n + 1}, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) t[i][j] = a[i] === b[j] ? t[i+1][j+1] + 1 : Math.max(t[i+1][j], t[i][j+1]);
  let i = 0, j = 0, out = "";
  while (i < n && j < m) { if (a[i] === b[j]) { out += esc(a[i]); i++; j++; } else if (t[i+1][j] >= t[i][j+1]) { out += "<del>" + esc(a[i++]) + "</del>"; } else { out += "<ins>" + esc(b[j++]) + "</ins>"; } }
  while (i < n) out += "<del>" + esc(a[i++]) + "</del>"; while (j < m) out += "<ins>" + esc(b[j++]) + "</ins>";
  return out;
}
const base = item => { const f = item.previous_final || {}, b = item.previous_blind || {}; return f.status === "verified" ? (f.text || "") : (b.text || ""); };
function entry(item){ return state.items[item.id] ??= {opened_at: now(), history: []}; }
function progress(){
  const done = CFG.items.filter(i => state.items[i.id]?.decided_at).length;
  document.getElementById("progress").innerHTML = `Đã quyết định: <b>${done}/${CFG.items.length}</b>`;
}
function render(){
  const box = document.getElementById("items"); box.innerHTML = "";
  CFG.items.forEach((item, k) => {
    const e = entry(item), pb = item.previous_blind || {}, pf = item.previous_final || {};
    const regionNow = e.region ?? (pf.status === "verified" ? pf.region : "printed_text");
    const section = document.createElement("section");
    section.innerHTML = `<h2>${esc(item.where)}</h2><p class="note">ID: <code>${esc(item.id)}</code></p>
      <div><button class="act" data-z="1">1×</button><button class="act" data-z="2">2×</button><button class="act" data-z="3">3×</button></div>
      <p class="note">Ảnh đã dùng khi gõ mù (vạch đỏ bên trái đánh dấu dòng):</p>
      <div class="view"><img class="img" src="${item.image}" alt="ảnh dòng"></div>
      <p class="note">Cùng vùng ảnh, render lại từ PDF ở ${Math.round(item.sharp_zoom * 72)} DPI cho nét hơn:</p>
      <div class="view"><img class="img" src="${item.sharp}" alt="ảnh nét hơn"></div>
      <table><tr><th>Bản gõ mù của bạn (khóa lúc ${esc(pb.locked_at)})</th><td class="txt">${pb.status === "typed" ? esc(pb.text) : "<i>(" + esc(pb.status) + ")</i>"}</td></tr>
      <tr><th>Quyết định cuối của bạn (${esc(pf.status)}, lúc ${esc(pf.decided_at)})</th><td class="txt">${pf.text ? diff(pb.text, pf.text) : "<i>—</i>"}${pf.note ? '<div class="note">Lý do khi đó: ' + esc(pf.note) + "</div>" : ""}</td></tr></table>
      <fieldset><legend>Xác minh lại dòng này</legend>
        <label><input type="radio" name="a${k}" value="confirm" ${e.action === "confirm" ? "checked" : ""}> Xác nhận: quyết định cuối ở trên là đúng</label><br>
        <label><input type="radio" name="a${k}" value="correct" ${e.action === "correct" ? "checked" : ""}> Sửa: văn bản đúng là (chỉ sửa ký tự sai, không cần gõ lại cả dòng)</label><br>
        <textarea class="text">${esc(e.action === "correct" ? e.text : base(item))}</textarea>
        <div class="note">Khác với quyết định cuối: <span class="live txt"></span></div>
        <label>Loại vùng: <select class="region">${CFG.regions.map(r => `<option ${r === regionNow ? "selected" : ""}>${r}</option>`).join("")}</select></label><br>
        <label><input type="radio" name="a${k}" value="uncertain" ${e.action === "uncertain" ? "checked" : ""}> Không chắc (uncertain): dòng này không được dùng để chấm</label><br>
        <input class="reason" placeholder="Lý do (bắt buộc), ví dụ: phóng 3× thấy dấu nặng dưới chữ ..." value="${esc(e.reason ?? "")}">
        <button class="act primary decide">Lưu quyết định dòng này</button>
        <p class="status">${e.decided_at ? `<span class="done">Đã lưu lúc ${esc(e.decided_at)}: ${esc(e.action)}</span>` : '<span class="todo">Chưa quyết định</span>'}</p>
      </fieldset>`;
    box.appendChild(section);
    section.querySelectorAll("[data-z]").forEach(b => b.onclick = () => section.querySelectorAll("img.img").forEach(img => {
      img.style.transform = `scale(${b.dataset.z})`; img.parentElement.style.height = (img.naturalHeight * b.dataset.z + 14) + "px"; }));
    const area = section.querySelector("textarea.text"), live = section.querySelector(".live");
    const update = () => { const text = clean(area.value); live.innerHTML = text === clean(base(item)) ? "<i>(giống hệt)</i>" : diff(base(item), text); };
    area.oninput = update; update();
    section.querySelector(".decide").onclick = () => {
      const action = section.querySelector(`input[name="a${k}"]:checked`)?.value;
      const reason = section.querySelector("input.reason").value.trim();
      if (!action) { alert("Chọn Xác nhận, Sửa hoặc Không chắc."); return; }
      if (!reason) { alert("Ghi lý do trước khi lưu."); return; }
      let text = null, region = pf.region ?? null;
      if (action === "correct") {
        text = clean(area.value); region = section.querySelector("select.region").value;
        if (!text) { alert("Văn bản sửa đang trống."); return; }
        if (pf.status === "verified" && text === clean(pf.text)) { alert("Văn bản giống hệt quyết định cuối: hãy chọn Xác nhận."); return; }
        if (pb.status !== "typed") { alert("Lượt gõ mù không đọc được: chỉ được chọn Không chắc."); return; }
      }
      if (action === "uncertain") region = "uncertain";
      const decided_at = now();
      Object.assign(e, {action, text, region, reason, decided_at});
      e.history.push({action, text, region, reason, decided_at});
      render(); };
  });
  progress();
}
document.getElementById("title").textContent = CFG.title;
document.getElementById("reviewer").oninput = ev => state.reviewer = ev.target.value.trim();
document.getElementById("save").onclick = () => {
  if (!state.reviewer) { alert("Nhập ID người review trước khi tải JSON."); return; }
  const missing = CFG.items.filter(i => !state.items[i.id]?.decided_at);
  if (missing.length) { alert("Còn " + missing.length + " dòng chưa quyết định."); return; }
  const items = {};
  CFG.items.forEach(i => { const e = state.items[i.id]; items[i.id] = {image_sha256: i.image_sha256, previous_blind: i.previous_blind,
    previous_final: i.previous_final, action: e.action, text: e.action === "correct" ? e.text : null, region: e.region,
    reason: e.reason, opened_at: e.opened_at, decided_at: e.decided_at, history: e.history}; });
  const data = {schema: CFG.addendum_schema, page_id: CFG.page_id, page_sha256: CFG.page_sha256, queue_id: CFG.queue_id,
    queue_sha256: CFG.queue_sha256, base_export_sha256: CFG.base_export_sha256, base_export_file: CFG.base_export_file,
    reviewer: state.reviewer, page_opened_at: PAGE_OPENED, exported_at: now(), items};
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: "application/json"}));
  a.download = `${CFG.page_id}.json`; a.click(); };
render();
</script></body></html>
"""


if __name__ == "__main__":
    raise SystemExit(main())

"""Blind evaluation of the frozen candidate H1 against A0: register, run-h1, select, queue, score.

No step runs unless the H1 freeze verifies (experiments.hybrid_h1.freeze). Run from
repo root (Windows CMD), and only after the user has authorized a blind round:

  1. A0 of every blind PDF with the frozen engine, into a new directory:
       .venv-demo\\Scripts\\python.exe -m demo.local_pdf_ocr.quality.e2e_regression ^
         --rerun-only <pdf> [--rerun-only <pdf> ...] --output-dir <round>\\a0
  2. ...python.exe -m experiments.hybrid_h1.blind register --freeze <freeze_manifest.json> ^
         --round-dir <round> --pair <pdf> <round>\\a0\\<stem>.rerun.json [--pair ...]
  3. ... blind run-h1 --freeze <...> --round-dir <round> --confirm-blind-round
  4. ... blind select --freeze <...> --round-dir <round>
  5. ... blind queue  --freeze <...> --round-dir <round>
     A person types every queue blind (offline HTML pages in <round>\\queues) and
     saves each export into <round>\\exports.
  6. ... blind score  --freeze <...> --round-dir <round>

A queue page shows line images only: no A0, no H1, no PDF text layer, no label,
and never whether a line is in the representative or the changed-lines set. The
PDF text layer is never a reference. Every step writes new files only and stops
on any hash difference. ``--rehearsal`` (register) accepts already-used PDFs to
test the tools; such a round is marked REHEARSAL_NOT_BLIND and is never evidence.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from demo.local_pdf_ocr.quality import gt_v2
from demo.local_pdf_ocr.quality.vietdoc_review40 import agency_names

from . import freeze as frozen
from .evaluate_h1 import line_order_unchanged
from .score_paired import score as score_rows
from .score_paired import verdict as decide

REPO = Path(__file__).resolve().parents[2]
NON_BLIND = REPO / "demo/local_pdf_ocr/quality_work/vietdoc_gtv2_crop_geometry_v1/experiment_sources.json"
EMPTY_REVEAL = {"v1_label": None, "v1_status": None, "v1_region": None, "ocr_original": None, "pdf_text_layer": None,
                "evidence": ""}
SETS = ("changed", "representative")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def seeded(tag: str, pdf_sha: str) -> random.Random:
    return random.Random(int(hashlib.sha256(f"{tag}|{pdf_sha}".encode("utf-8")).hexdigest(), 16))


def write_new(path: Path, data: dict) -> None:
    if path.exists():
        raise ValueError(f"STOP: will not overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def round_sources(round_dir: Path, manifest: dict) -> dict:
    data = load(round_dir / "blind_sources.json")
    if data["freeze_manifest_sha256"] != manifest["_manifest_sha256"]:
        raise ValueError("STOP: the round was registered under another freeze")
    for source in data["sources"]:
        if (frozen.sha256_file(Path(source["pdf"])) != source["pdf_sha256"]
                or frozen.sha256_file(Path(source["ocr_json"])) != source["ocr_json_sha256"]):
            raise ValueError(f"STOP: {source['document']} changed since registration")
    return data


# ------------------------------------------------------------------ steps

def register(freeze: Path, round_dir: Path, pairs: list[tuple[Path, Path]], *, non_blind: Path = NON_BLIND,
             rehearsal: bool = False) -> dict:
    manifest = frozen.require(freeze)
    used = {s["pdf_sha256"] for s in load(non_blind)["sources"]}
    sources, seen = [], set()
    for pdf, a0 in pairs:
        pdf_sha, a0_sha = frozen.sha256_file(pdf), frozen.sha256_file(a0)
        if pdf_sha in seen or Path(pdf).name in {s["document"] for s in sources}:
            raise ValueError(f"STOP: {pdf} is registered twice (same content or name)")
        seen.add(pdf_sha)
        if pdf_sha in used and not rehearsal:
            raise ValueError(f"STOP: {Path(pdf).name} was already used for design or evaluation; it cannot be blind")
        export = load(a0)
        expected = {"method": "vietocr_ocr", "model": manifest["b1024"]["selected"],
                    "detection_model": "PP-OCRv6_medium_det", "header_split_enabled": True}
        wrong = {k: export.get(k) for k, v in expected.items() if export.get(k) != v}
        if wrong:
            raise ValueError(f"STOP: {a0} is not an A0 output of the frozen pipeline: {wrong}")
        sources.append({"set": "rehearsal_not_blind" if rehearsal else "blind", "document": Path(pdf).name,
                        "pdf": str(pdf), "ocr_json": str(a0), "pdf_sha256": pdf_sha, "ocr_json_sha256": a0_sha,
                        "pages": export["page_count"], "lines": export["line_count"]})
    data = {"schema": "h1_blind_sources_v1", "kind": "REHEARSAL_NOT_BLIND" if rehearsal else "BLIND",
            "registered_at": now(), "freeze_manifest_sha256": manifest["_manifest_sha256"], "sources": sources}
    write_new(round_dir / "blind_sources.json", data)
    return {"kind": data["kind"], "sources": len(sources), "lines": sum(s["lines"] for s in sources)}


def run_h1(freeze: Path, round_dir: Path, *, confirm: bool = False) -> dict:
    manifest = frozen.require(freeze)
    data = round_sources(round_dir, manifest)
    if data["kind"] == "BLIND" and not confirm:
        raise ValueError("STOP: running H1 on blind documents needs --confirm-blind-round")
    from . import hybrid

    # The frozen hybrid.run(), unchanged. Its design-time refusal of the reserved document is
    # lifted here only, for a registered round under a verified freeze.
    refusal = hybrid.refuse_reserved
    hybrid.refuse_reserved = lambda name: None
    try:
        result = hybrid.run(data["sources"], round_dir / "h1")
    finally:
        hybrid.refuse_reserved = refusal
    # The run hashed the bytes it ran: they must still be on disk and, line endings aside, be the frozen candidate.
    ran = {name: frozen.sha256_file(hybrid.HERE / name) for name in hybrid.CODE_FILES}
    candidate = {Path(p).name: h for p, h in manifest["files"]["candidate"].items() if Path(p).name in hybrid.CODE_FILES}
    if result["code_sha256"] != ran or {name: frozen.frozen_sha256(hybrid.HERE / name) for name in hybrid.CODE_FILES} != candidate:
        raise RuntimeError("STOP: the run used code other than the frozen candidate")
    path = round_dir / "h1" / "h1_run_manifest.json"
    run_manifest = load(path)
    run_manifest.update({"blind_set_used": data["kind"] == "BLIND",
                         "round": {"kind": data["kind"], "freeze_manifest_sha256": manifest["_manifest_sha256"],
                                   "sources_sha256": frozen.sha256_file(round_dir / "blind_sources.json")}})
    path.write_text(json.dumps(run_manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"kind": data["kind"], "lines": sum(s["lines"] for s in result["sources"]),
            "selected": sum(s["selected"] for s in result["sources"])}


def select(freeze: Path, round_dir: Path) -> dict:
    manifest = frozen.require(freeze)
    criteria = manifest["criteria"]["selection"]
    data = round_sources(round_dir, manifest)
    run_manifest = load(round_dir / "h1" / "h1_run_manifest.json")
    decisions = [json.loads(line) for line in (round_dir / "h1" / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    documents, total = [], 0
    for source in data["sources"]:
        lines = [d for d in decisions if d["document"] == source["document"]]
        if len(lines) != source["lines"]:
            raise ValueError(f"STOP: H1 decided {len(lines)} of {source['lines']} lines of {source['document']}")
        keys = [d["key"] for d in lines]
        changed = [d["key"] for d in lines if d["text"] != d["b1024_text"]]
        size = min(criteria["representative_lines_per_pdf"], len(keys))
        representative = sorted(seeded("h1-blind-v1", source["pdf_sha256"]).sample(keys, size), key=keys.index)
        order = sorted(set(changed) | set(representative), key=keys.index)
        seeded("h1-blind-v1-order", source["pdf_sha256"]).shuffle(order)
        pages = next(s["pages"] for s in run_manifest["sources"] if s["document"] == source["document"])
        native = sum(p["class"] == "native_text" for p in pages)
        prefix = "h1_rehearsal" if data["kind"] != "BLIND" else "h1_blind"
        documents.append({"document": source["document"], "pdf_sha256": source["pdf_sha256"],
                          "group": "born_digital" if native * 2 >= len(pages) else "scanned",
                          "lines": len(keys), "changed": changed, "representative": representative,
                          "queue_order": order, "queue_id": f"{prefix}_{source['pdf_sha256'][:12]}"})
        total += len(order)
    if total > criteria["max_items_per_round"]:
        raise ValueError(f"STOP: {total} items exceed max_items_per_round; register fewer PDFs")
    selection = {"schema": "h1_blind_selection_v1", "kind": data["kind"], "created_at": now(),
                 "freeze_manifest_sha256": manifest["_manifest_sha256"],
                 "sources_sha256": frozen.sha256_file(round_dir / "blind_sources.json"),
                 "decisions_sha256": frozen.sha256_file(round_dir / "h1" / "decisions.jsonl"),
                 "h1_json_sha256": {s["document"]: s["h1_json_sha256"] for s in run_manifest["sources"]},
                 "rule": criteria, "documents": documents}
    write_new(round_dir / "blind_selection.json", selection)
    return {"documents": len(documents), "items": total, "changed": sum(len(d["changed"]) for d in documents),
            "representative": sum(len(d["representative"]) for d in documents)}


def checked_selection(round_dir: Path, manifest: dict) -> dict:
    selection = load(round_dir / "blind_selection.json")
    if (selection["freeze_manifest_sha256"] != manifest["_manifest_sha256"]
            or selection["sources_sha256"] != frozen.sha256_file(round_dir / "blind_sources.json")
            or selection["decisions_sha256"] != frozen.sha256_file(round_dir / "h1" / "decisions.jsonl")):
        raise ValueError("STOP: the selection does not match the registered round and its H1 run")
    for document, digest in selection["h1_json_sha256"].items():
        if frozen.sha256_file(round_dir / "h1" / "documents" / f"{Path(document).stem}.h1.json") != digest:
            raise ValueError(f"STOP: the H1 output of {document} changed")
    return selection


def queue(freeze: Path, round_dir: Path) -> dict:
    manifest = frozen.require(freeze)
    data = round_sources(round_dir, manifest)
    selection = checked_selection(round_dir, manifest)
    sources = {s["document"]: s for s in data["sources"]}
    index = {}
    for doc in selection["documents"]:
        source = sources[doc["document"]]
        export = load(source["ocr_json"])
        polygons = {(p["page"], l["line_index"]): l["polygon"] for p in export["pages"] for l in p["lines"]}
        items = []
        for key in doc["queue_order"]:
            _, page, line = key.rsplit("|", 2)
            page, line = int(page), int(line)
            items.append({"id": f"{doc['pdf_sha256'][:10]}_p{page:03d}_l{line:03d}", "kind": "h1_blind",
                          "required": True, "priority": "high", "document": doc["document"], "page": page,
                          "line_index": line, "image": gt_v2.context_view(Path(source["pdf"]), page, polygons[(page, line)]),
                          "reveal": dict(EMPTY_REVEAL)})
        title = ("REHEARSAL (not blind) — " if data["kind"] != "BLIND" else "H1 blind — ") + doc["document"]
        result = gt_v2.write_queue(items, round_dir / "queues", doc["queue_id"], title)
        index[doc["queue_id"]] = {"document": doc["document"], "queue_sha256": result["queue_sha256"],
                                  "items": result["items"], "html": Path(result["html"]).name}
    write_new(round_dir / "queues" / "queues_index.json", {"schema": "h1_blind_queues_v1", "created_at": now(),
                                                           "kind": data["kind"], "queues": index})
    return {"queues": len(index), "items": sum(q["items"] for q in index.values())}


def score(freeze: Path, round_dir: Path, exports_dir: Path | None = None) -> dict:
    manifest = frozen.require(freeze)
    data = round_sources(round_dir, manifest)
    selection = checked_selection(round_dir, manifest)
    out = round_dir / "score"
    if out.exists():
        raise ValueError(f"STOP: will not overwrite {out} (a round is scored once)")
    index = load(round_dir / "queues" / "queues_index.json")["queues"]
    exports = {}
    for path in sorted((exports_dir or round_dir / "exports").glob("*.json")):
        export = load(path)
        if export.get("queue_id") in exports:
            raise ValueError(f"STOP: two exports for queue {export['queue_id']}")
        exports[export.get("queue_id")] = (path, export)
    decisions = {}
    for line in (round_dir / "h1" / "decisions.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        decisions[record["key"]] = record
    problems, rows, rows_blind, excluded, reviewers = [], [], [], Counter(), set()
    for doc in selection["documents"]:
        queue_path = round_dir / "queues" / f"{doc['queue_id']}.queue.json"
        queue_bytes = queue_path.read_bytes()
        queue_sha = hashlib.sha256(queue_bytes).hexdigest()
        if queue_sha != index[doc["queue_id"]]["queue_sha256"]:
            problems.append(f"{doc['queue_id']}: queue file changed")
            continue
        if doc["queue_id"] not in exports:
            problems.append(f"{doc['queue_id']}: no export")
            continue
        queue_data = json.loads(queue_bytes)
        if any(any(v for k, v in item["reveal"].items()) for item in queue_data["items"]):
            problems.append(f"{doc['queue_id']}: the queue revealed machine text")
            continue
        found, bad, missing = gt_v2.validate_export(queue_data, queue_sha, exports[doc["queue_id"]][1])
        problems += [f"{doc['queue_id']}: {p}" for p in bad] + [f"{doc['queue_id']}: {m} has no decision" for m in missing]
        reviewers.add(exports[doc["queue_id"]][1].get("reviewer"))
        for item in queue_data["items"]:
            decision = found.get(item["id"])
            if decision is None:
                continue
            key = f"{item['document']}|{item['page']}|{item['line_index']}"
            final, blind = decision["final"], decision["blind"]
            if final["status"] != "verified":
                excluded[final["status"]] += 1
                continue
            row = {"key": key, "document": doc["document"], "group": doc["group"],
                   "sets": [s for s in SETS if key in doc[s]], "a0": decisions[key]["b1024_text"], "h1": decisions[key]["text"]}
            rows.append({**row, "reference": final["text"]})
            if blind["status"] == "typed":
                rows_blind.append({**row, "reference": blind["text"]})
    if problems:  # nothing is scored, so the one scoring of the round is not used up
        report = {"schema": "h1_blind_score_v1", "kind": data["kind"], "status": "BLOCKED", "problems": problems,
                  "scored": False, "checked_at": now()}
        path = round_dir / f"score_BLOCKED_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}.json"
        write_new(path, report)
        return {"status": "BLOCKED", "problems": len(problems), "report": str(path)}
    out.mkdir(parents=True)
    agencies = agency_names()
    primary, sensitivity = score_rows(rows, agencies), score_rows(rows_blind, agencies)
    run_manifest = load(round_dir / "h1" / "h1_run_manifest.json")
    order = line_order_unchanged(round_dir / "h1", run_manifest, {s["document"]: s for s in data["sources"]})
    integrity = {
        "freeze_verified": True,
        "fallback_byte_identical": all(d["text"].encode() == d["b1024_text"].encode() for d in decisions.values() if d["source"] == "b1024"),
        "line_order_and_polygons_identical": order["order_or_polygon_mismatches"] == 0,
        "exports_valid_and_complete": True,
    }
    items = sum(len(d["queue_order"]) for d in selection["documents"])
    inputs = {"pdfs": len(selection["documents"]),
              "born_digital_pdfs": sum(d["group"] == "born_digital" for d in selection["documents"]),
              "excluded_share": sum(excluded.values()) / items if items else 1.0}
    result = decide(primary["metrics"], sensitivity["metrics"], manifest["criteria"], integrity, inputs)
    report = {
        "schema": "h1_blind_score_v1", "kind": data["kind"], "status": "SCORED", "scored_at": now(),
        "verdict": result["verdict"] if data["kind"] == "BLIND" else "REHEARSAL_NOT_EVIDENCE",
        "verdict_rule_result": result, "freeze_manifest_sha256": manifest["_manifest_sha256"],
        "reviewers": sorted(r for r in reviewers if r), "items": items, "excluded": dict(excluded),
        "sufficiency_inputs": inputs, "integrity": integrity, "line_order": order,
        "references": "human blind transcriptions; primary = final text, sensitivity = blind-locked text; never the PDF text layer",
        "primary": primary["metrics"], "sensitivity_blind_locked": sensitivity["metrics"],
    }
    (out / "blind_metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    with (out / "blind_paired_lines.csv").open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["key", "document", "group", "sets", "status", "a0_char_errors", "h1_char_errors", "reference_chars",
                         "h1_differs", "key_fields_changed"])
        for p in primary["pairs"]:
            writer.writerow([p["key"], p["document"], p["group"], "+".join(p["sets"]), p["status"], p["a0_char_errors"],
                             p["h1_char_errors"], p["chars"], p["h1_differs"],
                             "; ".join(f"{f['type']}:{'A0 wrong' if f['a0_wrong'] else 'A0 ok'}->{'H1 wrong' if f['h1_wrong'] else 'H1 ok'}"
                                       for f in p["key_fields"] if f["a0_wrong"] != f["h1_wrong"])])
    with (out / "blind_key_field_changes.csv").open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["key", "document", "type", "text", "a0_wrong", "h1_wrong"])
        writer.writeheader()
        writer.writerows(primary["key_field_changes"])
    return {"status": "SCORED", "verdict": report["verdict"], "scored_lines": len(rows)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("register", "run-h1", "select", "queue", "score"):
        sub = commands.add_parser(name)
        sub.add_argument("--freeze", type=Path, required=True, help="freeze_manifest.json written by experiments.hybrid_h1.freeze")
        sub.add_argument("--round-dir", type=Path, required=True)
        if name == "register":
            sub.add_argument("--pair", nargs=2, type=Path, action="append", required=True, metavar=("PDF", "A0_JSON"))
            sub.add_argument("--non-blind", type=Path, default=NON_BLIND)
            sub.add_argument("--rehearsal", action="store_true", help="tool test on used PDFs; never evidence")
        if name == "run-h1":
            sub.add_argument("--confirm-blind-round", action="store_true")
        if name == "score":
            sub.add_argument("--exports-dir", type=Path)
    args = parser.parse_args(argv)
    if args.command == "register":
        result = register(args.freeze, args.round_dir, [tuple(p) for p in args.pair], non_blind=args.non_blind,
                          rehearsal=args.rehearsal)
    elif args.command == "run-h1":
        result = run_h1(args.freeze, args.round_dir, confirm=args.confirm_blind_round)
    elif args.command == "select":
        result = select(args.freeze, args.round_dir)
    elif args.command == "queue":
        result = queue(args.freeze, args.round_dir)
    else:
        result = score(args.freeze, args.round_dir, args.exports_dir)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

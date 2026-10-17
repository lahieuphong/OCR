"""Evaluate candidate H1 against A0 (frozen B1024) on independent human labels only.

Run from repo root (Windows CMD):
  .venv-demo\\Scripts\\python.exe -m experiments.hybrid_h1.evaluate_h1 --work-dir <dir> --labels-v1 <labels.json>

<dir> holds h1_preregistration.json and h1_run/. The PDF text layer is never a
reference here: it is H1's own source. References are the 40-line pack labels v1
(trusted partition), review_01 and review_numbers_02. Writes hybrid_h1_metrics.json
and hybrid_h1_regressions.csv into <dir>, never over existing files. Stops if the
run's code or gates differ from the pre-registration.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from demo.local_pdf_ocr.quality.benchmark import metrics, nfc, sha256
from demo.local_pdf_ocr.quality.vietdoc_review40 import agency_names, entity_spans, error_spans, hard_case_entries
from experiments.crop_geometry.evaluate import (
    CANARIES, date_spans, document_group, human_references, line_measures, sign_test,
)

from .freeze import frozen_sha256
from .hybrid import CODE_FILES, HERE, gates_sha256

REPO = Path(__file__).resolve().parents[2]
KEY_FIELDS = ("doc_number", "email", "agency_name", "date")
SETS = {"REG-H40T": "REG-H40", "REG-H72": "REG-H72", "REG-H5": "REG-H5"}
OLD8 = ("old8_calibration", "old8_holdout")
LABELS_V2_SCHEMA = "vietdoc_holdout_manual_review_v2"


def quantiles(values: list[float], points=(0.0, 0.05, 0.5, 0.95, 1.0)) -> dict:
    values = sorted(values)
    if not values:
        return {}
    return {f"p{int(q * 100)}": round(values[round(q * (len(values) - 1))], 4) for q in points}


def labels_v2_references(path: Path) -> dict[str, str]:
    """document|page|line_index -> reference for every verified line of a labels v2 file (gt_v2 labels-v2)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != LABELS_V2_SCHEMA:
        raise ValueError(f"STOP: {path} is not a labels v2 file")
    return {f"{r['document']}|{r['page']}|{r['line_index']}": r["review"]["reference"] for r in data["labels"]
            if r["review"].get("status") == "verified" and isinstance(r["review"].get("reference"), str)}


def key_fields(text: str, agencies: list[str]) -> Counter:
    return Counter((s["type"], s["text"]) for s in entity_spans(text, agencies) + date_spans(nfc(text)))


def compare(name: str, references: dict[str, str], decisions: dict[str, dict], agencies, entries) -> tuple[dict, list[dict]]:
    keys = sorted(k for k in references if k in decisions)
    result = {"lines": len(keys), "references_without_run": sorted(k for k in references if k not in decisions)}
    if not keys:
        return result, []
    a0 = {k: line_measures(references[k], decisions[k]["b1024_text"], agencies, entries) for k in keys}
    h1 = {k: line_measures(references[k], decisions[k]["text"], agencies, entries) for k in keys}
    improved = [k for k in keys if h1[k]["char_errors"] < a0[k]["char_errors"]]
    regressed = [k for k in keys if h1[k]["char_errors"] > a0[k]["char_errors"]]
    fields = {}
    for kind in KEY_FIELDS:
        fields[kind] = {
            "instances": sum(a0[k]["entities"].get(kind, 0) for k in keys),
            "A0_with_error": sum(a0[k]["entities_wrong"].get(kind, 0) for k in keys),
            "H1_with_error": sum(h1[k]["entities_wrong"].get(kind, 0) for k in keys),
            "new_errors_vs_A0": sum(max(0, h1[k]["entities_wrong"].get(kind, 0) - a0[k]["entities_wrong"].get(kind, 0)) for k in keys),
            "fixed_vs_A0": sum(max(0, a0[k]["entities_wrong"].get(kind, 0) - h1[k]["entities_wrong"].get(kind, 0)) for k in keys),
        }
    canary_lost = sorted(f"{k}#{w}" for k in keys for w, ok in a0[k]["canary_correct"].items() if ok and not h1[k]["canary_correct"].get(w, False))
    result.update({
        "A0": metrics([(references[k], decisions[k]["b1024_text"]) for k in keys]),
        "H1": metrics([(references[k], decisions[k]["text"]) for k in keys]),
        "H1_lines_from_text_layer": sum(decisions[k]["source"] == "pdf_text" for k in keys),
        "H1_lines_text_differs_from_A0": sum(decisions[k]["text"] != decisions[k]["b1024_text"] for k in keys),
        "improved": len(improved), "regressed": len(regressed), "unchanged": len(keys) - len(improved) - len(regressed),
        "sign_test": sign_test(len(improved), len(regressed)),
        "key_fields": fields, "canary_regressions": canary_lost,
        "by_group": {group: {"lines": sum(document_group(k.split("|")[0]) == group for k in keys),
                             "A0_char_errors": sum(a0[k]["char_errors"] for k in keys if document_group(k.split("|")[0]) == group),
                             "H1_char_errors": sum(h1[k]["char_errors"] for k in keys if document_group(k.split("|")[0]) == group),
                             "improved": sum(document_group(k.split("|")[0]) == group for k in improved),
                             "regressed": sum(document_group(k.split("|")[0]) == group for k in regressed)}
                     for group in ("born_digital", "scanned")},
    })
    rows = []
    for k in keys:
        d = decisions[k]
        if d["text"] == d["b1024_text"]:
            continue
        status = "improved" if k in improved else "regressed" if k in regressed else "changed_same_char_errors"
        new_fields = {kind: max(0, h1[k]["entities_wrong"].get(kind, 0) - a0[k]["entities_wrong"].get(kind, 0)) for kind in KEY_FIELDS}
        rows.append({"set": name, "key": k, "group": document_group(k.split("|")[0]), "status": status,
                     "reference": references[k], "a0_text": d["b1024_text"], "h1_text": d["text"], "h1_source": d["source"],
                     "a0_char_errors": a0[k]["char_errors"], "h1_char_errors": h1[k]["char_errors"],
                     "new_key_field_errors": ";".join(f"{kind}:{n}" for kind, n in new_fields.items() if n),
                     "a0_spans": " | ".join(f"{s['reference']}→{s['hypothesis']}" for s in error_spans(references[k], d["b1024_text"])),
                     "h1_spans": " | ".join(f"{s['reference']}→{s['hypothesis']}" for s in error_spans(references[k], d["text"]))})
    return result, rows


def unlabelled_key_field_changes(decisions: dict[str, dict], labelled: set[str], agencies) -> list[dict]:
    rows = []
    for k, d in sorted(decisions.items()):
        if k in labelled or d["text"] == d["b1024_text"]:
            continue
        before, after = key_fields(d["b1024_text"], agencies), key_fields(d["text"], agencies)
        lost, gained = before - after, after - before
        if lost or gained:
            rows.append({"set": "unlabelled", "key": k, "group": document_group(k.split("|")[0]),
                         "status": "unlabelled_key_field_change", "reference": "", "a0_text": d["b1024_text"],
                         "h1_text": d["text"], "h1_source": d["source"], "a0_char_errors": "", "h1_char_errors": "",
                         "new_key_field_errors": "",
                         "a0_spans": " | ".join(f"{t}:{s}" for (t, s) in sorted(lost)),
                         "h1_spans": " | ".join(f"{t}:{s}" for (t, s) in sorted(gained))})
    return rows


def line_order_unchanged(run_dir: Path, manifest: dict, sources: dict[str, dict]) -> dict:
    checked = mismatched = 0
    for source in manifest["sources"]:
        a0 = json.loads(Path(sources[source["document"]]["ocr_json"]).read_text(encoding="utf-8"))
        h1 = json.loads((run_dir / "documents" / f"{Path(source['document']).stem}.h1.json").read_text(encoding="utf-8"))
        for pa, ph in zip(a0["pages"], h1["pages"]):
            checked += len(pa["lines"])
            mismatched += sum((la["line_index"], la["polygon"]) != (lh["line_index"], lh["polygon"]) for la, lh in zip(pa["lines"], ph["lines"]))
            mismatched += abs(len(pa["lines"]) - len(ph["lines"]))
    return {"lines_checked": checked, "order_or_polygon_mismatches": mismatched}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--labels-v1", type=Path, required=True)
    parser.add_argument("--v1-dir", type=Path, default=REPO / "demo/local_pdf_ocr/quality_work/vietdoc_5pdf_review40_eval_v1")
    parser.add_argument("--sources", type=Path, default=REPO / "demo/local_pdf_ocr/quality_work/vietdoc_gtv2_crop_geometry_v1/experiment_sources.json")
    parser.add_argument("--tests-summary", type=Path, help="JSON {suites: [{suite, tests_run, result}]} of the related test runs (G5)")
    parser.add_argument("--labels-v2", type=Path, help="labels v2 (gt_v2 labels-v2): its verified lines replace REG-H40T")
    parser.add_argument("--run-dir", type=Path, help="frozen H1 run (default <work-dir>/h1_run)")
    parser.add_argument("--preregistration", type=Path, help="default <work-dir>/h1_preregistration.json")
    args = parser.parse_args(argv)
    work, run_dir = args.work_dir, args.run_dir or args.work_dir / "h1_run"
    targets = (work / "hybrid_h1_metrics.json", work / "hybrid_h1_regressions.csv")
    if any(t.exists() for t in targets):
        raise ValueError("STOP: evaluation outputs already exist")
    prereg = json.loads((args.preregistration or work / "h1_preregistration.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "h1_run_manifest.json").read_text(encoding="utf-8"))
    current = {name: frozen_sha256(HERE / name) for name in CODE_FILES}  # line endings aside
    frozen = {"run_gates_match": manifest["gates_sha256"] == prereg["gates_sha256"],
              "run_code_matches": manifest["code_sha256"] == prereg["code_sha256"],
              "current_code_matches": current == prereg["code_sha256"] and gates_sha256() == prereg["gates_sha256"]}
    if not all(frozen.values()):
        raise ValueError(f"STOP: H1 changed after registration: {frozen}")
    decisions = {}
    for line in (run_dir / "decisions.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        decisions[record["key"]] = record
    fallback = [d for d in decisions.values() if d["source"] == "b1024"]
    fallback_identity = {"fallback_lines": len(fallback),
                         "fallback_lines_not_byte_identical_to_A0": sum(d["text"].encode() != d["b1024_text"].encode() for d in fallback)}
    sources = {s["document"]: s for s in json.loads(args.sources.read_text(encoding="utf-8"))["sources"]}
    agencies, entries = agency_names(), sorted(set(hard_case_entries()) | set(CANARIES))
    references = human_references(args.v1_dir, args.labels_v1, REPO / "demo/local_pdf_ocr/quality_work")
    h40_source = "labels v1 trusted partition (pending_recheck + uncertain excluded)"
    if args.labels_v2:
        references["REG-H40"] = labels_v2_references(args.labels_v2)
        h40_source = f"labels v2 verified lines ({args.labels_v2.name}, sha256 {sha256(args.labels_v2)})"
    results, rows = {}, []
    for name, source_name in SETS.items():
        results[name], set_rows = compare(name, references[source_name], decisions, agencies, entries)
        rows += set_rows
    pooled, conflicts = {}, []
    for source_name in SETS.values():
        for k, reference in references[source_name].items():
            if k in pooled and pooled[k] != reference:
                conflicts.append(k)
            pooled.setdefault(k, reference)
    for group in ("born_digital", "scanned"):
        subset = {k: v for k, v in pooled.items() if document_group(k.split("|")[0]) == group}
        results[f"POOLED-{group}"], _ = compare(f"POOLED-{group}", subset, decisions, agencies, entries)
    results["POOLED-all"], _ = compare("POOLED-all", pooled, decisions, agencies, entries)
    old8_docs = {d for d, s in sources.items() if s["set"] in OLD8}
    results["REG-8PDF-labelled"], _ = compare("REG-8PDF-labelled", {k: v for k, v in pooled.items() if k.split("|")[0] in old8_docs},
                                              decisions, agencies, entries)
    unlabelled_rows = unlabelled_key_field_changes(decisions, set(pooled), agencies)
    rows += unlabelled_rows

    def rates(items: list[dict]) -> dict:
        n = len(items)
        chosen = sum(d["source"] == "pdf_text" for d in items)
        return {"lines": n, "from_text_layer": chosen, "fallback": n - chosen,
                "selection_rate": round(chosen / n, 4) if n else None,
                "selected_text_differs_from_A0": sum(d["source"] == "pdf_text" and d["text"] != d["b1024_text"] for d in items)}

    every = list(decisions.values())
    old8 = [d for d in every if d["set"] in OLD8]
    per_document = {}
    for doc in sorted({d["document"] for d in every}):
        per_document[doc] = {**rates([d for d in every if d["document"] == doc]), "group": document_group(doc),
                             "page_classes": dict(Counter(p["class"] for s in manifest["sources"] if s["document"] == doc for p in s["pages"]))}
    selected = [d for d in every if d["source"] == "pdf_text"]
    with_words = [d for d in every if d.get("text_layer_deviation")]
    timing = []
    for s in manifest["sources"]:
        pages = len(s["pages"])
        a0_pages = [ms for ms in s["a0_page_elapsed_ms"] if isinstance(ms, (int, float))]
        timing.append({"document": s["document"], "pages": pages, "h1_total_ms": s["h1_total_ms"], "h1_render_ms": s["h1_render_ms"],
                       "h1_ms_per_page": round(s["h1_total_ms"] / pages, 1),
                       "a0_ms_per_page": round(sum(a0_pages) / len(a0_pages), 1) if a0_pages else None})
    report = {
        "schema": "hybrid_h1_metrics_v1", "candidate": prereg["candidate"], "preregistration_registered_at": prereg["registered_at"],
        "frozen_check": frozen, "gates_sha256": prereg["gates_sha256"], "code_sha256": prereg["code_sha256"],
        "references": {"REG-H40T": h40_source, "REG-H72": "review_01 verified",
                       "REG-H5": "review_numbers_02 verified", "text_layer": "never used as a reference for H1",
                       "pooled_reference_conflicts": conflicts, "DEV-human": "NOT AVAILABLE -> NOT EVALUATED",
                       "BLIND": "NOT AVAILABLE -> NOT EVALUATED (30.signed.pdf reserved, never read)"},
        "normalization": "NFC; micro Levenshtein CER/WER; no case folding or punctuation removal",
        "human_labelled": results,
        "fallback_identity": fallback_identity,
        "line_order": line_order_unchanged(run_dir, manifest, sources),
        "selection": {"all_15": rates(every), "old8": rates(old8),
                      "by_group": {g: rates([d for d in every if document_group(d["document"]) == g]) for g in ("born_digital", "scanned")},
                      "by_page_class": {c: rates([d for d in every if d["page_class"] == c]) for c in sorted({d["page_class"] for d in every})},
                      "fallback_first_reason": dict(Counter(d["fallback_reason"] for d in every if d["fallback_reason"]).most_common()),
                      "fallback_any_gate": dict(Counter(g for d in every for g in d["failed_gates"]).most_common()),
                      "per_document": per_document},
        "unlabelled_key_field_changes": {"lines": len(unlabelled_rows),
                                         "old8_lines": sum(r["key"].split("|")[0] in old8_docs for r in unlabelled_rows)},
        "position": {"selected_iou": quantiles([d["text_layer_deviation"]["iou"] for d in selected]),
                     "selected_abs_edge_offset_px": quantiles([abs(v) for d in selected for v in d["text_layer_deviation"]["offset_px"]]),
                     "lines_with_text_layer_words_iou": quantiles([d["text_layer_deviation"]["iou"] for d in with_words]),
                     "selected_stream_order_differs": sum(d["checks"].get("stream_order_differs", False) for d in selected),
                     "page_visible_words_outside_every_polygon": sum(p["visible_words_outside_every_polygon"] for s in manifest["sources"] for p in s["pages"])},
        "timing": {"per_document": timing,
                   "h1_ms_per_page_overall": round(sum(t["h1_total_ms"] for t in timing) / sum(t["pages"] for t in timing), 1),
                   "note": "H1 overhead only (text layer, gates, engine render for ink checks); B1024 still runs on every line for fallback and the consistency gates, so H1 time = A0 time + overhead. A0 per-page times come from the stored exports / reruns (different sessions and thread counts)."},
    }
    tests = json.loads(args.tests_summary.read_text(encoding="utf-8")) if args.tests_summary else None
    report["related_tests"] = tests or "NOT RUN"
    p = results["POOLED-all"]
    scanned = results["POOLED-scanned"]
    go = {
        "G1_improvement_on_human_labels": p["H1"]["char_errors"] < p["A0"]["char_errors"] and p["improved"] > p["regressed"],
        "G2_no_new_key_field_errors": all(r["key_fields"][kind]["new_errors_vs_A0"] == 0 for name, r in results.items()
                                          if name in SETS and r.get("lines") for kind in KEY_FIELDS),
        "G3_fallback_byte_identical": fallback_identity["fallback_lines_not_byte_identical_to_A0"] == 0 and report["line_order"]["order_or_polygon_mismatches"] == 0,
        "G4_scans_not_degraded": scanned["H1"]["char_errors"] <= scanned["A0"]["char_errors"] and scanned["regressed"] == 0,
        "G5_related_tests_green": (all(s["result"] == "OK" and s["tests_run"] > 0 for s in tests["suites"]) if tests else "NOT RUN"),
        "G6_frozen_before_evaluation": all(frozen.values()),
    }
    report["go_criteria"] = go
    report["verdict"] = "ELIGIBLE_FOR_BLIND_ROUND" if all(v is True for v in go.values()) else "NOT_ELIGIBLE"
    work.mkdir(parents=True, exist_ok=True)
    (work / "hybrid_h1_metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with (work / "hybrid_h1_regressions.csv").open("x", encoding="utf-8-sig", newline="") as stream:
        fields = ["set", "key", "group", "status", "reference", "a0_text", "h1_text", "h1_source", "a0_char_errors",
                  "h1_char_errors", "new_key_field_errors", "a0_spans", "h1_spans"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        order = {"regressed": 0, "unlabelled_key_field_change": 1, "changed_same_char_errors": 2, "improved": 3}
        for row in sorted(rows, key=lambda r: (order[r["status"]], r["set"], r["key"])):
            writer.writerow(row)
    summary = {name: {k: r.get(k) for k in ("lines", "improved", "regressed", "H1_lines_from_text_layer")} |
               ({"A0_cer": round(r["A0"]["cer"], 5), "H1_cer": round(r["H1"]["cer"], 5)} if "A0" in r else {})
               for name, r in results.items()}
    print(json.dumps({"verdict": report["verdict"], "go": go, "sets": summary, "fallback_identity": fallback_identity}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

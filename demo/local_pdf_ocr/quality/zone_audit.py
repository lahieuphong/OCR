"""Local-only verified region tags and candidate ledger (never changes OCR output).

Default labels have NO reviewed region tag: unknown != printed.
A region tag is accepted only after an explicit human save from review UI.
Original OCR benchmark metrics always remain visible; the printed subset
is a separate sensitivity analysis, NOT a replacement for whole-document CER.
"""
from __future__ import annotations

import argparse
from collections import Counter
import html
import json
import os
from pathlib import Path
from urllib.parse import quote

from .benchmark import distance, metrics, nfc, verified_samples
from .error_analysis import verify_previous_report


REGION_TYPES = {
    "printed_text": "Chữ in thông thường",
    "stamp_overlap": "Chữ bị con dấu che/đè",
    "stamp_artifact": "Chỉ là con dấu/hình, không phải dòng văn bản",
    "handwriting": "Chữ viết tay",
    "uncertain": "Chưa thể xác định từ ảnh",
}


def normalized_region(label: dict) -> str:
    """Legacy rows are unreviewed; no inference from OCR text or geometry."""
    reviewed = label.get("region_reviewed") is True
    region = label.get("region_type")
    if reviewed and region in REGION_TYPES:
        return region
    if reviewed or region not in (None, ""):
        raise ValueError("Invalid/unreviewed region classification; re-open editor")
    return "unreviewed"


def score_subset(lines: list[dict]) -> dict | None:
    if not lines:
        return None
    return metrics([(r["reference"], r["ocr_prediction"]) for r in lines])


def verified_region_rows(samples: list[dict], labels: list[dict]) -> list[dict]:
    annotations = {}
    for label in labels:
        ident = label.get("id")
        if ident in annotations:
            raise ValueError("Duplicate region label")
        annotations[ident] = label
    rows = []
    for item in samples:
        label = annotations.get(item["id"])
        if label is None:
            raise ValueError("Region label missing")
        rows.append({**item, "region_type": normalized_region(label)})
    return rows


def candidate_ledger(work_dir: Path, rows: list[dict]) -> list[dict]:
    """Read existing per-line ONNX predictions; NEVER rerun or select automatically."""
    source = work_dir / "error_analysis.json"
    if not source.exists():
        return []
    report = json.loads(source.read_text(encoding="utf-8"))
    if (report.get("summary", {}).get("no_blind_test") is not True
            or report.get("summary", {}).get("selected_baseline_reproduced") is not True
            or report.get("summary", {}).get("candidate_inference_performed") is not True):
        raise ValueError("Targeted ONNX error report not verified")
    known = {row["id"]: row for row in rows}
    ledger = []
    seen = set()
    for entry in report.get("lines", []):
        ident = entry["id"]
        if ident in seen or ident not in known:
            raise ValueError("Unknown or repeated candidate sample ID")
        seen.add(ident)
        original = known[ident]
        if (entry.get("reference") != original["reference"]
                or entry.get("baseline") != original["ocr_prediction"]
                or entry.get("crop_sha256") != original["crop_sha256"]):
            raise ValueError(f"Stale candidate/ground truth evidence for {ident}")
        before_c = distance(nfc(original["reference"]), nfc(original["ocr_prediction"]))
        before_w = distance(nfc(original["reference"]).split(),
                            nfc(original["ocr_prediction"]).split())
        details = []
        for name, prediction in entry.get("variants", {}).items():
            if name not in {"contrast_1p15", "unsharp_light", "autocontrast_1pct"}:
                raise ValueError("Unknown transform")
            result = prediction.get("prediction")
            if not isinstance(result, str):
                raise ValueError("Variant predictions missing")
            char_errors = distance(nfc(original["reference"]), nfc(result))
            word_errors = distance(nfc(original["reference"]).split(), nfc(result).split())
            if (prediction.get("char_errors") != char_errors
                    or prediction.get("word_errors") != word_errors):
                raise ValueError("Stale variant scoring found")
            details.append({
                "name": name, "prediction": result,
                "char_delta": char_errors - before_c,
                "word_delta": word_errors - before_w,
                "improves_both_or_ties_wer": char_errors < before_c and word_errors <= before_w,
                "worsens_either": char_errors > before_c or word_errors > before_w,
            })
        ledger.append({
            "id": ident,
            "document": original.get("document", ""),
            "page": original.get("page"),
            "crop_path": original["crop_path"],
            "baseline": original["ocr_prediction"],
            "reference": original["reference"],
            "region_type": original["region_type"],
            "baseline_char_errors": before_c,
            "baseline_word_errors": before_w,
            "variants": sorted(details, key=lambda d: (d["char_delta"], d["word_delta"], d["name"])),
            "automatic_choice_approved": False,
            "requires_original_document_review": True,
        })
    return ledger


def build_zone_audit(work_dir: Path, min_verified: int = 20) -> dict:
    samples = verified_samples(work_dir, min_verified=min_verified)
    previous = verify_previous_report(work_dir, samples)
    from .benchmark import read_jsonl

    rows = verified_region_rows(samples, read_jsonl(work_dir / "labels.jsonl"))
    buckets = {name: [] for name in (*REGION_TYPES.keys(), "unreviewed")}
    for row in rows:
        buckets[row["region_type"]].append(row)
    ledger = candidate_ledger(work_dir, rows)
    groups = {}
    for key, members in buckets.items():
        groups[key] = {
            "count": len(members),
            "baseline_metrics": score_subset(members),
        }
    candidates_improved = [
        {"id": entry["id"], "document": entry["document"],
         "variants": [candidate["name"] for candidate in entry["variants"]
                      if candidate["improves_both_or_ties_wer"]]}
        for entry in ledger
        if any(c["improves_both_or_ties_wer"] for c in entry["variants"])
    ]
    return {
        "summary": {
            "status": "EXPERIMENTAL_REVIEW_ONLY",
            "verified_lines": len(rows),
            "region_reviewed_lines": len(rows) - len(buckets["unreviewed"]),
            "region_unreviewed_lines": len(buckets["unreviewed"]),
            "original_all_line_metrics": previous["scores"]["baseline"],
            "printed_text_only_metrics": groups["printed_text"]["baseline_metrics"],
            "candidate_lines_with_local_improvement": len(candidates_improved),
            "candidate_count": len(ledger),
            "candidate_inference_performed_by_this_script": False,
            "no_automatic_recognition_replacement": True,
            "blind_test_used": False,
            "merge_approved": False,
            "note": (
                "Region-aware metrics are a sensitivity check only. "
                "No unknown/stamp/handwritten rows are silently reclassified, "
                "and no alternative text is chosen for document output."
            ),
        },
        "region_types": REGION_TYPES,
        "groups": groups,
        "possible_local_improvements": candidates_improved,
        "candidate_ledger": ledger,
    }


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def render_html(report: dict) -> str:
    summary = report["summary"]
    cells = []
    for e in report["candidate_ledger"]:
        src = quote(e["crop_path"].replace("\\", "/"), safe="/")
        if not src.startswith("crops/"):
            raise ValueError("Unexpected crop path")
        comparisons = "".join(
            "<tr><td>" + esc(v["name"]) + "</td><td>" + esc(v["prediction"]) +
            "</td><td>" + esc(v["char_delta"]) +
            "</td><td>" + esc(v["word_delta"]) + "</td></tr>"
            for v in e["variants"]
        )
        cells.append(
            '<article><h2>' + esc(e["document"]) + ' · trang ' +
            esc(e["page"]) + '</h2><p class="sub">' + esc(e["id"]) +
            ' · loại vùng: <strong>' + esc(e["region_type"]) +
            '</strong></p><img src="' + esc(src) +
            '" alt="Đoạn ảnh OCR được cắt từ PDF"><div class="pair"><div><b>Ảnh đã xác minh</b><p>' +
            esc(e["reference"]) + '</p></div><div><b>VietOCR B ban đầu</b><p>' +
            esc(e["baseline"]) + '</p></div></div>'
            '<table><thead><tr><th>Biến thể</th><th>Dự đoán</th>'
            '<th>Δ lỗi ký tự</th><th>Δ lỗi từ</th></tr></thead><tbody>' +
            comparisons + '</tbody></table><p class="sub">Ứng viên chỉ để so sánh; '
            'không tự động thay nội dung OCR.</p></article>'
        )
    return (
        '<!doctype html><html lang="vi"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>VietOCR · Vùng ảnh & ứng viên</title><style>'
        'body{font:15px system-ui;background:#f4f6fa;color:#1e293b}'
        'main{max-width:1100px;margin:auto;padding:20px}article{border:1px solid #dde5ef;'
        'background:white;border-radius:10px;padding:16px;margin:18px 0}'
        'img{max-width:100%;margin:12px 0;background:white;border:1px solid #ccd}'
        '.pair{display:grid;grid-template-columns:1fr 1fr;gap:10px}'
        '.pair>div{background:#f1f5fb;padding:10px;border-radius:8px}'
        'p{overflow-wrap:anywhere;white-space:pre-wrap}'
        'table{width:100%;border-collapse:collapse;table-layout:fixed}'
        'td,th{border:1px solid #ccd;padding:8px;text-align:left;overflow-wrap:anywhere}'
        '.sub{font-size:12px;color:#526275}'
        '@media(max-width:650px){.pair{grid-template-columns:1fr}}'
        '</style><main><h1>Vùng OCR & đối chiếu ứng viên</h1>'
        '<p>Đã kiểm chứng ' + esc(summary["verified_lines"]) +
        ' dòng; phân loại vùng thủ công ' + esc(summary["region_reviewed_lines"]) +
        '; vùng chưa phân loại ' + esc(summary["region_unreviewed_lines"]) +
        '. Không thay đổi văn bản OCR hoặc merge main.</p>'
        '<p><b>Chú ý:</b> sửa một dòng cục bộ không chứng minh biến thể '
        'tốt hơn toàn bộ PDF. Các vùng dấu và hình phải được xem ảnh gốc.</p>'
        + "".join(cells) + "</main></html>"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--min-verified", type=int, default=20)
    args = parser.parse_args(argv)
    report = build_zone_audit(args.work_dir, min_verified=args.min_verified)
    out = args.work_dir / "zone_audit.json"
    web = args.work_dir / "zone_audit.html"
    # Only overwrite previously derived QA artifacts. Keep source labels intact.
    for target, data in (
        (out, json.dumps(report, ensure_ascii=False, indent=2)),
        (web, render_html(report)),
    ):
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, target)
    print(json.dumps({
        **report["summary"],
        "json_file": str(out), "html_file": str(web),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

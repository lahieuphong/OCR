"""Private/local triage of verified OCR errors and experiment regressions.

Run from repo root:
  .venv-demo\Scripts\python.exe -m demo.local_pdf_ocr.quality.error_analysis ^
    --work-dir demo\local_pdf_ocr\quality_work\review_01

Add --with-variants to rerun ONLY selected existing crops through frozen
ONNX; NEVER reruns detector, PDFs, blind test, model training, or changes UI.
Report stays next to private labels. No OCR text is pushed to GitHub.
"""
from __future__ import annotations

import argparse
import difflib
import html
import json
import os
import re
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import quote

from .benchmark import VARIANTS, distance, metrics, nfc, sha256, transform, verified_samples


def without_diacritics(text: str) -> str:
    base = unicodedata.normalize("NFD", nfc(text))
    return "".join(c for c in base if not unicodedata.combining(c))


def difference_tags(reference: str, prediction: str) -> list[str]:
    """Describe visible character differences, NOT their physical causes."""
    ref, pred = nfc(reference), nfc(prediction)
    if ref == pred:
        return ["unchanged"]
    tags = []
    if without_diacritics(ref) == without_diacritics(pred):
        tags.append("diacritic_only")
    if re.findall(r"\d+", ref) != re.findall(r"\d+", pred):
        tags.append("digit_sequence_differs")
    if [c for c in ref if unicodedata.category(c).startswith("P")] != [
        c for c in pred if unicodedata.category(c).startswith("P")
    ]:
        tags.append("punctuation_differs")
    if ref.split() != pred.split() and "".join(ref.split()) == "".join(pred.split()):
        tags.append("spacing_only")
    if not tags:
        tags.append("other_character_or_sequence_difference")
    return tags


def edits(reference: str, prediction: str) -> list[dict]:
    """Character-level edit spans from GT to OCR; human-inspect manually."""
    ref, pred = nfc(reference), nfc(prediction)
    return [
        {"operation": op, "reference": ref[a:b], "ocr": pred[c:d]}
        for op, a, b, c, d in difflib.SequenceMatcher(
            a=ref, b=pred, autojunk=False
        ).get_opcodes()
        if op != "equal"
    ]


def verify_previous_report(work_dir: Path, samples: list[dict]) -> dict:
    source = work_dir / "benchmark_report.json"
    if not source.is_file():
        raise ValueError(
            "Missing benchmark_report.json. Run the frozen baseline benchmark "
            "first; labels alone cannot establish previous regressions."
        )
    report = json.loads(source.read_text(encoding="utf-8"))
    if (report.get("status") != "EXPERIMENT_ONLY_NO_DEPLOYMENT_APPROVAL"
            or report.get("blind_test_used") is not False
            or report.get("baseline_reproduced_exactly") is not True
            or report.get("samples_human_verified") != len(samples)):
        raise ValueError("Previous report contract or sample count mismatch")
    computed = metrics([(row["reference"], row["ocr_prediction"]) for row in samples])
    if computed != report.get("scores", {}).get("baseline"):
        raise ValueError(
            "STOP: labels or predictions differ from previous benchmark. "
            "Do not compare new GT against stale regression metrics."
        )
    from demo.local_pdf_ocr.backend.contract import CHECKPOINT_SHA256
    if report.get("frozen_checkpoint_sha256") != CHECKPOINT_SHA256:
        raise ValueError("Previous benchmark checkpoint hash mismatch")
    return report


def select_focus(samples: list[dict], report: dict) -> tuple[list[dict], list[dict]]:
    regressions = {}
    for variant, assessment in report.get("candidate_assessment", {}).items():
        if variant not in VARIANTS[1:]:
            raise ValueError("Unknown benchmark variant in previous report")
        for identifier in assessment.get("new_regression_line_ids", []):
            regressions.setdefault(identifier, []).append(variant)
    ids = {row["id"] for row in samples}
    if set(regressions) - ids:
        raise ValueError("Benchmark regression IDs absent from verified labels")
    incorrect = [r for r in samples if nfc(r["reference"]) != nfc(r["ocr_prediction"])]
    focused = [r for r in samples if r in incorrect or r["id"] in regressions]
    records = []
    for r in focused:
        gt, original = r["reference"], r["ocr_prediction"]
        records.append({
            "id": r["id"],
            "document": r.get("document", ""),
            "page": r.get("page"),
            "line_index": r.get("line_index"),
            "crop_path": r["crop_path"],
            "crop_sha256": r["crop_sha256"],
            "reference": gt,
            "baseline": original,
            "baseline_char_errors": distance(nfc(gt), nfc(original)),
            "baseline_word_errors": distance(nfc(gt).split(), nfc(original).split()),
            "difference_tags": difference_tags(gt, original),
            "character_edits": edits(gt, original),
            "regressed_variants_previous": sorted(regressions.get(r["id"], [])),
            "header_split": r.get("header_split", False),
            "layout_region": r.get("layout_region", ""),
            "manual_root_cause_required": True,
            "root_cause": None,
            "variants": {},
        })
    return records, incorrect


def infer_selected(records: list[dict], samples: list[dict]) -> None:
    """Only rerun the selected existing images, and fail on baseline mismatch."""
    from PIL import Image
    from demo.local_pdf_ocr.backend.contract import verify_frozen_onnx
    from demo.local_pdf_ocr.backend.engine import OnnxVietocrB

    metadata = verify_frozen_onnx(require_weights=True)
    recognizer = OnnxVietocrB(metadata)
    lookup = {r["id"]: r for r in samples}
    # Check baseline exact for ALL selected images before any variant.
    pictures = {}
    for item in records:
        row = lookup[item["id"]]
        with Image.open(row["_crop_path"]) as img:
            picture = img.convert("RGB")
        predicted, hit = recognizer.predict(picture)
        if hit or predicted != item["baseline"]:
            raise RuntimeError(
                "STOP: targeted frozen baseline mismatch: " + item["id"]
            )
        pictures[item["id"]] = picture
    # Only evaluate variants after the selected baseline is reproduced exactly.
    for item in records:
        ref = nfc(item["reference"])
        old_char = item["baseline_char_errors"]
        old_word = item["baseline_word_errors"]
        for variant in VARIANTS[1:]:
            output, hit = recognizer.predict(transform(pictures[item["id"]], variant))
            if hit:
                raise RuntimeError("Decoder limit in candidate: " + item["id"])
            char_error = distance(ref, nfc(output))
            word_error = distance(ref.split(), nfc(output).split())
            item["variants"][variant] = {
                "prediction": output,
                "char_errors": char_error,
                "word_errors": word_error,
                "char_delta": char_error - old_char,
                "word_delta": word_error - old_word,
                "changed": output != item["baseline"],
            }


def build_report(work_dir: Path, *, with_variants=False, min_verified=20) -> dict:
    samples = verified_samples(work_dir, min_verified=min_verified)
    old = verify_previous_report(work_dir, samples)
    records, incorrect = select_focus(samples, old)
    if not incorrect:
        raise ValueError("No human-verified OCR errors to analyze")
    if with_variants:
        infer_selected(records, samples)
    regressions = {
        variant: len(meta.get("new_regression_line_ids", []))
        for variant, meta in old["candidate_assessment"].items()
    }
    summary = {
        "status": "DIAGNOSTIC_ONLY_NO_AUTOMATIC_OCR_CHANGES",
        "all_verified_lines": len(samples),
        "baseline_errors": len(incorrect),
        "reviewed_candidate_regression_ids": len(records) - len(incorrect),
        "distinct_lines_in_report": len(records),
        "previous_candidate_regression_counts": regressions,
        "baseline_scores": old["scores"]["baseline"],
        "difference_tag_counts": dict(sorted(Counter(
            tag for item in records if item["baseline_char_errors"] > 0
            for tag in item["difference_tags"]
        ).items())),
        "selected_baseline_reproduced": bool(with_variants),
        "candidate_inference_performed": bool(with_variants),
        "no_blind_test": True,
        "no_merge_recommendation": True,
        "next_step": "Review image and exact error spans. Root cause is NOT inferred from spelling patterns.",
    }
    return {"summary": summary, "lines": records}


def escape(value) -> str:
    return html.escape(str(value), quote=True)


def render_html(report: dict) -> str:
    summary = report["summary"]
    boxes = []
    for row in report["lines"]:
        image = quote(str(row["crop_path"]).replace("\\", "/"), safe="/")
        if not image.startswith("crops/"):
            raise ValueError("Unexpected crop location")
        variants = "".join(
            '<tr><th>' + escape(name) + '</th><td class="mono">' +
            escape(row["variants"].get(name, {}).get("prediction", "Chưa chạy")) +
            '</td><td>' + escape(row["variants"].get(name, {}).get("char_delta", "—")) +
            '</td><td>' + escape(row["variants"].get(name, {}).get("word_delta", "—")) +
            '</td></tr>' for name in VARIANTS[1:]
        )
        edits_html = "".join(
            "<li>" + escape(part["operation"]) + ": <code>" +
            escape(part["reference"]) + "</code> → <code>" +
            escape(part["ocr"]) + "</code></li>"
            for part in row["character_edits"]
        )
        box = (
            '<article><div class="small">' + escape(row["id"]) +
            ' · ' + escape(row["document"]) + '</div>'
            '<img alt="OCR line crop" src="' + image + '">'
            '<div><b>Tham chiếu đã kiểm chứng</b><p class="text">' +
            escape(row["reference"]) + '</p></div>'
            '<div><b>VietOCR B ban đầu</b><p class="text">' +
            escape(row["baseline"]) + '</p></div>'
            '<p>Lỗi ký tự: ' + escape(row["baseline_char_errors"]) +
            ' · Lỗi từ: ' + escape(row["baseline_word_errors"]) +
            ' · Kiểu sai quan sát: ' + escape(", ".join(row["difference_tags"])) +
            '</p><ul>' + edits_html + '</ul>'
            '<p>Hồi quy theo benchmark cũ: ' +
            escape(", ".join(row["regressed_variants_previous"]) or "Không") + '</p>'
            '<table><thead><tr><th>Biến thể</th><th>Chữ nhận dạng</th>'
            '<th>Δ lỗi ký tự</th><th>Δ lỗi từ</th></tr></thead><tbody>' +
            variants + '</tbody></table>'
            '<p class="small">Nguyên nhân vật lý (con dấu, nét mờ, '
            'thiếu crop, mô hình): <b>chưa kết luận</b> — cần xem ảnh gốc.</p>'
            '</article>'
        )
        boxes.append(box)
    header = (
        '<!doctype html><html lang="vi"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>VietOCR · Phân tích lỗi thực tế</title><style>'
        'body{font:15px system-ui;background:#f3f5fb;color:#172239;margin:0}'
        'main{max-width:1150px;margin:0 auto;padding:22px}'
        'article{background:white;border:1px solid #dae2f0;'
        'border-radius:12px;padding:16px;margin:18px 0}'
        'img{display:block;max-width:100%;margin:15px 0;'
        'background:white;border:1px solid #ccc;padding:8px}'
        'table{border-collapse:collapse;width:100%;table-layout:fixed}'
        'th,td{border:1px solid #d8e1ef;text-align:left;padding:8px;'
        'overflow-wrap:anywhere}th{background:#edf1f9}'
        '.text{white-space:pre-wrap;overflow-wrap:anywhere}'
        '.small{font-size:12px;color:#586479;overflow-wrap:anywhere}'
        'code,.mono{font-family:Consolas,monospace;overflow-wrap:anywhere}'
        '</style><main><h1>Phân tích lỗi VietOCR — dữ liệu đã kiểm chứng</h1>'
        '<p>Chỉ là báo cáo phân tích, KHÔNG tự sửa OCR hoặc deploy. '
        'Các nhãn đã được kiểm chứng thủ công, nguồn ảnh lưu tại máy.</p>'
        '<p><b>' + escape(summary["baseline_errors"]) +
        '</b> dòng khác ground truth / ' + escape(summary["all_verified_lines"]) +
        ' dòng · ' + escape(summary["distinct_lines_in_report"]) +
        ' dòng cần rà soát (gồm các hồi quy ứng viên).</p>'
    )
    return header + "".join(boxes) + "</main></html>"


def write_reports(work_dir: Path, report: dict) -> tuple[Path, Path]:
    # Only generated analysis files are overwritten. Never touch labels, crops,
    # original benchmark report, PDFs, or the OCR output.
    json_file = work_dir / "error_analysis.json"
    html_file = work_dir / "error_analysis.html"
    for path, data in (
        (json_file, json.dumps(report, ensure_ascii=False, indent=2)),
        (html_file, render_html(report)),
    ):
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, path)
    return json_file, html_file


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--min-verified", type=int, default=20)
    parser.add_argument("--with-variants", action="store_true",
                        help="Run frozen ONNX ONLY on selected crops, not all PDFs")
    args = parser.parse_args(argv)
    report = build_report(
        args.work_dir, with_variants=args.with_variants, min_verified=args.min_verified
    )
    json_file, html_file = write_reports(args.work_dir, report)
    print(json.dumps({
        **report["summary"],
        "json_file": str(json_file),
        "html_file": str(html_file),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

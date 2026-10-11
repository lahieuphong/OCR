"""Model-free audit: flag suspicious document-number OCR WITHOUT changing text.

Works on an existing number_probe_with_holdout.json. Flags use ONLY the
baseline OCR and trial predictions, not filename, reference or document title.
Verified labels are consulted AFTER flagging for an offline flagging evaluation.

This is local reviewer assistance, not an automatic correction or production
gate. Numbers that look normal can still be wrong (false negatives).
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .benchmark import nfc
from .number_probe import VARIANTS, summarize_variants, validate_groups
from demo.local_pdf_ocr.backend.contract import CHECKPOINT_SHA256


PREFIX = re.compile(r"^\s*s[ốo]\s*[:.\-]\s*", flags=re.IGNORECASE)
SPACED_DIGITS = re.compile(r"^[0-9]+(?:\s+[0-9]+)+$")
DIGITS = re.compile(r"^[0-9]+$")
LETTERS = re.compile(r"[A-Za-z]")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
FLAG_LABELS = {
    "non_digit_serial": "Ký tự chữ trong phần số trước dấu / (VD: 1H9, RU6)",
    "split_digits": "Khoảng trắng chen giữa chữ số (VD: 2 1)",
    "empty_serial": "Không có số trước dấu /",
    "variant_disagreement": "OCR gốc và ít nhất một biến thể ảnh khác nhau",
}


def suspicious_flags(baseline: str, variants: dict[str, str]) -> list[str]:
    """No ground truth, filename, or external metadata allowed in this function."""
    if not isinstance(baseline, str) or not isinstance(variants, dict):
        raise ValueError("Invalid OCR prediction")
    found = []
    match = PREFIX.match(nfc(baseline))
    if match:
        serial = baseline[match.end():].split("/", 1)[0].strip()
        if not serial:
            found.append("empty_serial")
        elif SPACED_DIGITS.fullmatch(serial):
            found.append("split_digits")
        elif LETTERS.search(serial) and not DIGITS.fullmatch(serial):
            found.append("non_digit_serial")
    if any(
        value != baseline for key, value in variants.items()
        if key != "baseline"
    ):
        found.append("variant_disagreement")
    return found


def validate_report(report: dict) -> dict:
    if (report.get("status") != "OFFLINE_FIELD_PROBE_NOT_PRODUCTION"
            or report.get("model_sha256") != CHECKPOINT_SHA256
            or report.get("blind_test_used") is not False
            or report.get("production_model_modified") is not False
            or report.get("pdf_ocr_rerun") is not False
            or report.get("automatic_ocr_replacement") is not False
            or report.get("merge_approved") is not False):
        raise ValueError("STOP: unverifiable original frozen ONNX field probe")
    groups = report.get("all_predicted_lines")
    if not isinstance(groups, dict) or set(groups) != {"calibration", "holdout"}:
        raise ValueError("STOP: original per-line observations are missing")
    cal, holdout = groups["calibration"], groups["holdout"]
    if not isinstance(cal, list) or not cal or not isinstance(holdout, list):
        raise ValueError("STOP: invalid independent split")
    expected = {"calibration": report.get("calibration"), "holdout": report.get("holdout")}
    if not isinstance(expected["calibration"], dict):
        raise ValueError("STOP: missing original calibration metrics")
    split = validate_groups(cal, holdout)
    if report.get("split") != split:
        raise ValueError("STOP: PDF split data changed after original probe")
    seen = set()
    for kind, rows in (("calibration", cal), ("holdout", holdout)):
        for row in rows:
            ident = row.get("id")
            if not isinstance(ident, str) or not ident or ident in seen:
                raise ValueError("STOP: duplicate or empty crop ID")
            seen.add(ident)
            digest = row.get("pdf_sha256")
            if not isinstance(digest, str) or not SHA256.fullmatch(digest):
                raise ValueError("STOP: missing PDF SHA provenance")
            prediction = row.get("predictions")
            if (not isinstance(prediction, dict) or set(prediction) != set(VARIANTS)
                    or any(not isinstance(x, str) or not x.strip()
                           for x in prediction.values())
                    or prediction["baseline"] != row.get("ocr_original")
                    or not isinstance(row.get("reference"), str)
                    or not row["reference"].strip()
                    or row.get("auto_replace_approved") is not False):
                raise ValueError("STOP: invalid frozen ONNX observation")
        if rows:
            recalculated = summarize_variants(rows)
            recorded = expected[kind]
            if (not isinstance(recorded, dict) or
                    recalculated["scores"] != recorded.get("scores") or
                    recalculated["candidate_analysis"] != recorded.get("candidate_analysis")):
                raise ValueError("STOP: original metrics or predictions disagree with report")
        elif expected[kind] is not None:
            raise ValueError("STOP: holdout score provided without holdout crops")
    return split


def build_triage(report: dict) -> dict:
    split = validate_report(report)
    rows = []
    counters = {}
    for name in ("calibration", "holdout"):
        flagged_error = flagged_correct = missed_error = unflagged_correct = 0
        for entry in report["all_predicted_lines"][name]:
            raw = entry["ocr_original"]
            flags = suspicious_flags(raw, entry["predictions"])
            is_wrong = nfc(raw) != nfc(entry["reference"])
            if flags:
                if is_wrong:
                    flagged_error += 1
                else:
                    flagged_correct += 1
            else:
                if is_wrong:
                    missed_error += 1
                else:
                    unflagged_correct += 1
            rows.append({
                "id": entry["id"],
                "document": entry["document"],
                "dataset": name,
                "page": entry["page"],
                "ocr_original": raw,
                "flags": flags,
                "needs_human_review": bool(flags),
                "observed_ocr_error": is_wrong,
                "verified_reference": entry["reference"],
                "review_action": (
                    "CHECK_ORIGINAL_CROP_NO_AUTOMATIC_CORRECTION"
                    if flags else "NO_RULE_TRIGGERED_NOT_GUARANTEED_CORRECT"
                ),
                "replacement_text": None,
            })
        counters[name] = {
            "flagged_errors": flagged_error,
            "flagged_correct_lines": flagged_correct,
            "missed_errors": missed_error,
            "unflagged_correct_lines": unflagged_correct,
            "flagged": flagged_error + flagged_correct,
            "verified_errors": flagged_error + missed_error,
            "flag_recall_on_selected_verified_crops": (
                flagged_error / (flagged_error + missed_error)
                if flagged_error + missed_error else None
            ),
            "flag_precision_on_selected_verified_crops": (
                flagged_error / (flagged_error + flagged_correct)
                if flagged_error + flagged_correct else None
            ),
        }
    return {
        "status": "REVIEW_ONLY_NO_GO_FOR_AUTOMATIC_CORRECTION",
        "source": "existing frozen number_probe report; no ONNX inference performed",
        "model_sha256": report["model_sha256"],
        "split": split,
        "flags": FLAG_LABELS,
        "summary": counters,
        "rows": rows,
        "blind_test_used": False,
        "model_modified": False,
        "no_pdf_ocr_rerun": True,
        "no_reference_used_for_flagging": True,
        "no_filename_or_external_title_used_for_flagging": True,
        "automatic_correction_approved": False,
        "deployment_approved": False,
        "merge_approved": False,
        "known_limitations": [
            "This checks only selected document-number crops, not full-PDF retrieval recall.",
            "A clean-looking wrong number may not trigger a flag; manual review remains necessary.",
            "Flag metrics are retrospective on previously verified labels, not production accuracy.",
            "Only 5 independent holdout document numbers are available; never generalize success.",
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not args.input.is_file():
        parser.error("Missing original number probe JSON")
    result = build_triage(json.loads(args.input.read_text(encoding="utf-8")))
    target = args.output or args.input.with_name("number_triage.json")
    if target.exists():
        raise ValueError("STOP: output exists, choose another filename")
    if not target.parent.is_dir():
        raise ValueError("Output parent directory missing")
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "calibration": result["summary"]["calibration"],
        "holdout": result["summary"]["holdout"],
        "output": str(target),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Offline-only evaluation of document-number crops across independent PDFs.

Calibration reuses the already verified 72-crop review set.
A separate holdout directory is REQUIRED for any larger-trial eligibility.
No PDF re-OCR, model updates, hidden text correction, or blind-test use.

CLI:
  python -m demo.local_pdf_ocr.quality.number_probe --calibration-dir .../review_01
  python -m demo.local_pdf_ocr.quality.number_probe --calibration-dir .../review_01 --holdout-dir .../review_numbers_02
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .benchmark import distance, metrics, nfc, read_jsonl, transform, verified_samples
from .number_fields import is_document_number


VARIANTS = ("baseline", "contrast_1p15", "unsharp_light")
MIN_INDEPENDENT_HOLDOUT_DOCS = 5


def select_field_samples(work_dir: Path) -> list[dict]:
    """Select all header-number matches from manifest; refuse unreviewed rows.

    Selection never inspects ground truth. Fail closed if a candidate is
    unverified, not readable, altered, or a source PDF lacks SHA provenance.
    """
    manifest = read_jsonl(work_dir / "manifest.jsonl")
    candidate_ids = set()
    for row in manifest:
        if is_document_number(
            row, page=int(row["page"]), width=row.get("page_width"),
            height=row.get("page_height"),
        ):
            candidate_ids.add(row["id"])
    if not candidate_ids:
        raise ValueError(
            f"No document-number header candidates found in {work_dir}. "
            "Use --selection document_number and inspect the original PDF."
        )
    labels = {item["id"]: item for item in read_jsonl(work_dir / "labels.jsonl")}
    if any(labels.get(ident, {}).get("verified") is not True for ident in candidate_ids):
        raise ValueError(
            "Document-number crops remain unverified. Review each crop image "
            "in the local UI before any scoring."
        )
    if any(labels.get(ident, {}).get("region_type") == "stamp_artifact"
           and labels.get(ident, {}).get("region_reviewed") is True
           for ident in candidate_ids):
        raise ValueError(
            "STOP: a candidate is human-reviewed nontext stamp artwork; "
            "this field probe only scores actual text. Do not silently omit it."
        )
    verified = verified_samples(work_dir, min_verified=1)
    verified_by_id = {item["id"]: item for item in verified}
    if candidate_ids - verified_by_id.keys():
        raise ValueError(
            f"{len(candidate_ids - verified_by_id.keys())} document-number crops "
            "remain unverified. Open the local review UI and confirm each image."
        )
    selections = [item for item in verified if item["id"] in candidate_ids]
    for row in selections:
        digest = row.get("pdf_sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError("Missing PDF SHA for independent-document audit")
        if int(row["page"]) != 1:
            raise ValueError("Only page-1 document-number headers are eligible")
    return selections


def validate_groups(calibration: list[dict], holdout: list[dict]) -> dict:
    """Ensure split is by PDF SHA, not crop or filename, to avoid data leakage."""
    def by_pdf(rows: list[dict]) -> dict[str, str]:
        files = {}
        for row in rows:
            digest = row["pdf_sha256"]
            name = row.get("document", "")
            if digest in files and files[digest] != name:
                raise ValueError("Same PDF SHA appears under multiple filenames")
            files[digest] = name
        return files
    first = by_pdf(calibration)
    second = by_pdf(holdout)
    if first.keys() & second.keys():
        raise ValueError("STOP: calibration and holdout share PDF content SHA-256")
    return {
        "calibration_documents": len(first),
        "holdout_documents": len(second),
        "calibration_lines": len(calibration),
        "holdout_lines": len(holdout),
        "independent_holdout_gate_met": (
            len(second) >= MIN_INDEPENDENT_HOLDOUT_DOCS
            and len(holdout) >= MIN_INDEPENDENT_HOLDOUT_DOCS
        ),
    }


def summarize_variants(observations: list[dict]) -> dict:
    """Score all lines; a single worsened crop vetoes larger-trial eligibility."""
    if not observations:
        raise ValueError("No observations")
    scores = {}
    regression_ids = {}
    for variant in VARIANTS:
        scores[variant] = metrics([
            (item["reference"], item["predictions"][variant])
            for item in observations
        ])
    baseline = scores["baseline"]
    decisions = {}
    for variant in VARIANTS[1:]:
        worsening = []
        improved = []
        for row in observations:
            base = nfc(row["predictions"]["baseline"])
            trial = nfc(row["predictions"][variant])
            reference = nfc(row["reference"])
            old_char = distance(reference, base)
            new_char = distance(reference, trial)
            old_word = distance(reference.split(), base.split())
            new_word = distance(reference.split(), trial.split())
            if new_char > old_char or new_word > old_word:
                worsening.append(row["id"])
            if new_char < old_char and new_word <= old_word:
                improved.append(row["id"])
        regression_ids[variant] = worsening
        decisions[variant] = {
            "char_error_delta": scores[variant]["char_errors"] - baseline["char_errors"],
            "word_error_delta": scores[variant]["word_errors"] - baseline["word_errors"],
            "improved_line_ids": improved,
            "regressed_line_ids": worsening,
            "no_regressions": not worsening,
        }
    return {"scores": scores, "candidate_analysis": decisions}


def infer_verified(samples: list[dict], recognizer) -> list[dict]:
    from PIL import Image

    base_images = []
    mismatches = []
    for row in samples:
        with Image.open(row["_crop_path"]) as original:
            crop = original.convert("RGB")
        baseline, hit = recognizer.predict(crop)
        if hit or baseline != row["ocr_prediction"]:
            mismatches.append(row["id"])
        base_images.append((row, crop, baseline))
    if mismatches:
        raise RuntimeError(
            "STOP: frozen ONNX baseline parity mismatch before preprocessing: "
            + ", ".join(mismatches[:5])
        )

    output = []
    for row, crop, baseline in base_images:
        predictions = {"baseline": baseline}
        for variant in VARIANTS[1:]:
            proposal, truncated = recognizer.predict(transform(crop, variant))
            if truncated:
                raise RuntimeError(f"Decoder limit hit: {variant}, {row['id']}")
            predictions[variant] = proposal
        output.append({
            "id": row["id"],
            "document": row["document"],
            "pdf_sha256": row["pdf_sha256"],
            "page": row["page"],
            "reference": row["reference"],
            "ocr_original": baseline,
            "predictions": predictions,
            "auto_replace_approved": False,
        })
    return output


def decide_larger_trial(calibration: dict, holdout: dict | None,
                        split: dict) -> dict:
    if holdout is None:
        return {
            "status": "INSUFFICIENT_INDEPENDENT_DOCUMENTS",
            "eligible_for_larger_trial": False,
            "why": "Only calibration data is available; no independent holdout.",
        }
    advice = {}
    for variant in VARIANTS[1:]:
        c = calibration["candidate_analysis"][variant]
        h = holdout["candidate_analysis"][variant]
        advice[variant] = bool(
            split["independent_holdout_gate_met"]
            and c["no_regressions"] and h["no_regressions"]
            and h["char_error_delta"] < 0 and h["word_error_delta"] <= 0
            and calibration["scores"]["baseline"]["lines"] >= 3
        )
    return {
        "status": (
            "ELIGIBLE_FOR_LARGER_TRIAL_NOT_DEPLOYMENT"
            if any(advice.values()) else "NO_GO_FOR_LARGER_TRIAL"
        ),
        "eligible_for_larger_trial": any(advice.values()),
        "variant_eligibility": advice,
        "why": (
            "Requires 5+ independent holdout PDFs, zero per-line regressions "
            "on calibration AND holdout, strict holdout CER improvement "
            "and no WER increase. Never approves production replacement."
        ),
    }


def run_probe(calibration_dir: Path, holdout_dir: Path | None = None) -> dict:
    calibration = select_field_samples(calibration_dir)
    holdout = select_field_samples(holdout_dir) if holdout_dir is not None else []
    split = validate_groups(calibration, holdout)
    from demo.local_pdf_ocr.backend.contract import verify_frozen_onnx
    from demo.local_pdf_ocr.backend.engine import OnnxVietocrB

    metadata = verify_frozen_onnx(require_weights=True)
    recognizer = OnnxVietocrB(metadata)
    calibration_lines = infer_verified(calibration, recognizer)
    holdout_lines = infer_verified(holdout, recognizer) if holdout else []
    calibration_result = summarize_variants(calibration_lines)
    holdout_result = summarize_variants(holdout_lines) if holdout_lines else None
    decision = decide_larger_trial(calibration_result, holdout_result, split)
    return {
        "status": "OFFLINE_FIELD_PROBE_NOT_PRODUCTION",
        "model_sha256": metadata["checkpoint_sha256"],
        "blind_test_used": False,
        "production_model_modified": False,
        "pdf_ocr_rerun": False,
        "document_number_selection": "baseline-text prefix AND first-page geometry",
        "selection_limitations": (
            "OCR failures that omit the 'Số' prefix may be missed; "
            "field retrieval recall is NOT measured. Calibrated lines "
            "are not independent evidence of gain."
        ),
        "split": split,
        "calibration": calibration_result,
        "holdout": holdout_result,
        "decision": decision,
        "all_predicted_lines": {
            "calibration": calibration_lines,
            "holdout": holdout_lines,
        },
        "automatic_ocr_replacement": False,
        "merge_approved": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--calibration-dir", type=Path, required=True)
    parser.add_argument("--holdout-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = run_probe(args.calibration_dir, args.holdout_dir)
    target = args.output or args.calibration_dir / "number_probe.json"
    if target.exists():
        raise ValueError(
            f"STOP: {target} already exists. Choose a new output path; "
            "original reports and annotations are never overwritten."
        )
    if not target.parent.is_dir():
        raise ValueError(f"Output directory does not exist: {target.parent}")
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": report["decision"]["status"],
        "calibration_documents": report["split"]["calibration_documents"],
        "calibration_lines": report["split"]["calibration_lines"],
        "holdout_documents": report["split"]["holdout_documents"],
        "holdout_lines": report["split"]["holdout_lines"],
        "eligible_for_larger_trial": report["decision"]["eligible_for_larger_trial"],
        "output": str(target),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

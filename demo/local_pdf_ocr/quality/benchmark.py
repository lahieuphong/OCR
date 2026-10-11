"""Evaluate opt-in crop transforms using ONLY human-verified labels.

Never edits model checkpoint, production OCR code or frozen blind sets.
A candidate cannot be recommended unless the original crop run reproduces
its stored OCR prediction EXACTLY and no verified correct line regresses.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import unicodedata
from pathlib import Path


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def distance(a, b) -> int:
    """Levenshtein with O(min(n,m)) memory, for character or token lists."""
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            current.append(min(
                current[-1] + 1, previous[j] + 1,
                previous[j - 1] + int(char_a != char_b),
            ))
        previous = current
    return previous[-1]


def metrics(reference_predictions: list[tuple[str, str]]) -> dict:
    char_errors = chars = word_errors = words = exact = 0
    for reference, prediction in reference_predictions:
        ref, pred = nfc(reference), nfc(prediction)
        char_errors += distance(ref, pred)
        chars += len(ref)
        word_errors += distance(ref.split(), pred.split())
        words += len(ref.split())
        exact += int(ref == pred)
    if not reference_predictions or chars == 0 or words == 0:
        raise ValueError("No scoreable nonempty verified references")
    return {
        "lines": len(reference_predictions),
        "char_errors": char_errors,
        "reference_chars": chars,
        "cer": char_errors / chars,
        "word_errors": word_errors,
        "reference_words": words,
        "wer": word_errors / words,
        "exact_lines": exact,
        "exact_line_rate": exact / len(reference_predictions),
    }


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for piece in iter(lambda: stream.read(1 << 20), b""):
            h.update(piece)
    return h.hexdigest()


def verified_samples(work_dir: Path, *, min_verified: int = 20) -> list[dict]:
    """Fail closed on stale labels, extra IDs, missing SHA or unreviewed data."""
    if min_verified < 1:
        raise ValueError("min_verified must be >= 1")
    manifest = read_jsonl(work_dir / "manifest.jsonl")
    labels = read_jsonl(work_dir / "labels.jsonl")
    records = {}
    for row in manifest:
        if row["id"] in records:
            raise ValueError("Duplicate manifest id")
        records[row["id"]] = row
    by_id = {}
    for label in labels:
        if label["id"] in by_id or label["id"] not in records:
            raise ValueError("Duplicate/unknown label id")
        by_id[label["id"]] = label
    if set(records) != set(by_id):
        raise ValueError("Unpaired manifest and label IDs")
    verified = []
    for identifier, row in records.items():
        label = by_id[identifier]
        if label.get("crop_sha256") != row.get("crop_sha256"):
            raise ValueError(f"Crop sha in annotation differs: {identifier}")
        if label.get("verified") is not True:
            continue
        reference = label.get("reference")
        if not isinstance(reference, str) or not reference.strip():
            raise ValueError(f"Verified reference must be nonempty: {identifier}")
        if "\r" in reference or "\n" in reference:
            raise ValueError(f"Only one physical line per crop: {identifier}")
        relative = Path(row["crop_path"])
        root = work_dir.resolve()
        crop_path = (root / relative).resolve()
        if root not in crop_path.parents or crop_path.suffix.lower() != ".png":
            raise ValueError("Crop path escapes review directory")
        if sha256(crop_path) != row["crop_sha256"]:
            raise ValueError(f"Crop image changed after annotation: {identifier}")
        verified.append({**row, "reference": reference, "_crop_path": crop_path})
    if len(verified) < min_verified:
        raise ValueError(
            f"STOP: only {len(verified)} human-verified crops; require {min_verified}. "
            "Do not score OCR predictions as ground truth."
        )
    return verified


def transform(crop, variant: str):
    from PIL import ImageEnhance, ImageFilter

    if variant == "baseline":
        return crop
    if variant == "contrast_1p15":
        return ImageEnhance.Contrast(crop).enhance(1.15)
    if variant == "unsharp_light":
        return crop.filter(ImageFilter.UnsharpMask(radius=1, percent=80, threshold=3))
    if variant == "autocontrast_1pct":
        from PIL import ImageOps
        return ImageOps.autocontrast(crop, cutoff=1)
    raise ValueError(f"Unknown variant {variant}")


VARIANTS = ("baseline", "contrast_1p15", "unsharp_light", "autocontrast_1pct")


def run_benchmark(work_dir: Path, *, min_verified: int = 20) -> dict:
    """Only after verified reference count passes, load the frozen recognizer."""
    samples = verified_samples(work_dir, min_verified=min_verified)
    from PIL import Image

    from demo.local_pdf_ocr.backend.contract import verify_frozen_onnx
    from demo.local_pdf_ocr.backend.engine import OnnxVietocrB

    metadata = verify_frozen_onnx(require_weights=True)
    recognizer = OnnxVietocrB(metadata)
    observations: dict[str, list[tuple[str, str]]] = {name: [] for name in VARIANTS}
    by_sample = []
    mismatched_ids = []

    # Exact baseline recreation is a gate BEFORE trying enhanced crops.
    for row in samples:
        with Image.open(row["_crop_path"]) as src:
            image = src.convert("RGB")
            hypothesis, limit_hit = recognizer.predict(image)
        if limit_hit or hypothesis != row["ocr_prediction"]:
            mismatched_ids.append(row["id"])
        by_sample.append((row, image.copy(), hypothesis))
    if mismatched_ids:
        raise RuntimeError(
            f"STOP: frozen OCR baseline cannot be reproduced for "
            f"{len(mismatched_ids)} verified crops. Example IDs: "
            + ", ".join(mismatched_ids[:5]) + ". No transforms were scored."
        )

    per_variant_regressions = {name: [] for name in VARIANTS if name != "baseline"}
    for row, image, baseline in by_sample:
        observations["baseline"].append((row["reference"], baseline))
        base_error = distance(nfc(row["reference"]), nfc(baseline))
        for variant in VARIANTS[1:]:
            proposed, limit_hit = recognizer.predict(transform(image, variant))
            if limit_hit:
                raise RuntimeError(f"STOP: decoder limit reached {row['id']} {variant}")
            observations[variant].append((row["reference"], proposed))
            proposed_error = distance(nfc(row["reference"]), nfc(proposed))
            if proposed_error > base_error:
                per_variant_regressions[variant].append(row["id"])
    scores = {name: metrics(rows) for name, rows in observations.items()}
    baseline = scores["baseline"]
    advice = {}
    for variant in VARIANTS[1:]:
        result = scores[variant]
        advice[variant] = {
            "char_error_delta": result["char_errors"] - baseline["char_errors"],
            "word_error_delta": result["word_errors"] - baseline["word_errors"],
            "new_regression_line_ids": per_variant_regressions[variant],
            "eligible_for_larger_regression_trial": bool(
                result["char_errors"] < baseline["char_errors"]
                and result["word_errors"] <= baseline["word_errors"]
                and not per_variant_regressions[variant]
            ),
        }
    return {
        "status": "EXPERIMENT_ONLY_NO_DEPLOYMENT_APPROVAL",
        "samples_human_verified": len(samples),
        "blind_test_used": False,
        "frozen_checkpoint_sha256": metadata["checkpoint_sha256"],
        "inference_provider": "CPUExecutionProvider",
        "baseline_reproduced_exactly": True,
        "scores": scores,
        "candidate_assessment": advice,
        "production_recognizer_modified": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--min-verified", type=int, default=20)
    parser.add_argument("--validate-labels-only", action="store_true",
                        help="Check labels and integrity; do not load ONNX")
    args = parser.parse_args(argv)
    if args.validate_labels_only:
        samples = verified_samples(args.work_dir, min_verified=args.min_verified)
        print(f"PASS: {len(samples)} verified sample(s), crop hashes match. No OCR run.")
        return 0
    report = run_benchmark(args.work_dir, min_verified=args.min_verified)
    path = args.work_dir / "benchmark_report.json"
    if path.exists():
        raise ValueError("STOP: report already exists; create a new review directory for repeat experiment")
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Fail-closed PyTorch/CUDA-reference vs ONNX Runtime parity for frozen VietOCR B.

Windows CMD:
  .venv-vietocr\Scripts\python.exe datasets\vietnamese_recognition\check_vietocr_onnx_parity.py

Uses the 752 NON-BLIND crops and the frozen PyTorch inference predictions.
No blind image, ground truth or blind-test score may be used.
An exact text mismatch makes the full gate FAIL, with examples and a report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from export_vietocr_onnx import CHECKPOINT_SHA256, CONFIG, OUTPUT, WEIGHTS, sha256


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "eval_inputs.jsonl"
REFERENCE = ROOT / "predictions_exp_b_width1024.jsonl"
EXPECTED_SPLITS = {"real_val": 100, "synthetic_val": 552, "bakeoff_regression": 100}


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def validate_manifest(rows: list[dict]) -> None:
    from collections import Counter

    counts = Counter(row.get("split") for row in rows)
    if counts != EXPECTED_SPLITS:
        raise SystemExit(f"STOP: expected 752 non-blind rows {EXPECTED_SPLITS}, got {dict(counts)}")
    identifiers = [row["id"] for row in rows]
    if len(set(identifiers)) != len(identifiers):
        raise SystemExit("STOP: duplicate crop identifiers in parity manifest")


def verify_reference(rows: list[dict], predictions_path: Path) -> dict[str, str]:
    reference = read_jsonl(predictions_path)
    if len(reference) != len(rows):
        raise SystemExit(f"STOP: reference predictions have {len(reference)} records, expected {len(rows)}")
    names = [p["id"] for p in reference]
    if len(set(names)) != len(names) or set(names) != {row["id"] for row in rows}:
        raise SystemExit("STOP: reference prediction IDs do not match the non-blind manifest")
    meta_path = predictions_path.with_suffix(".meta.json")
    if not meta_path.is_file():
        raise SystemExit(f"STOP: missing PyTorch prediction metadata: {meta_path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if (meta.get("weights_sha256") != CHECKPOINT_SHA256
            or meta.get("image_max_width") != 1024
            or meta.get("decoder_max_seq_length") != 128):
        raise SystemExit("STOP: PyTorch reference metadata differs from frozen checkpoint/config")
    return {prediction["id"]: prediction["prediction"] for prediction in reference}


def verify_onnx_files(directory: Path, config_path: Path, weights_path: Path) -> dict:
    metadata_path = directory / "metadata.json"
    if not metadata_path.is_file():
        raise SystemExit(f"STOP: ONNX export metadata missing: {metadata_path}")
    info = json.loads(metadata_path.read_text(encoding="utf-8"))
    expected = {
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "config_sha256": sha256(config_path),
        "encoder_sha256": sha256(directory / "encoder.onnx"),
        "decoder_sha256": sha256(directory / "decoder_step.onnx"),
        "decoder_max_seq_length": 128,
        "image_max_width": 1024,
    }
    if sha256(weights_path) != CHECKPOINT_SHA256:
        raise SystemExit("STOP: local checkpoint differs from frozen selected model")
    for key, expected_value in expected.items():
        if info.get(key) != expected_value:
            raise SystemExit(f"STOP: ONNX metadata {key} does not match frozen export")
    if info.get("status") != "EXPORTED_NOT_YET_PARITY_VERIFIED":
        raise SystemExit("STOP: unexpected ONNX export status")
    return info


def predict_one(image, enc_session, dec_session, info: dict, vocab):
    import numpy as np
    from vietocr.tool.translate import process_input

    pixels = process_input(
        image, info["image_height"], info["image_min_width"], info["image_max_width"]
    ).numpy()
    memory = enc_session.run(["memory"], {"image": pixels})[0]
    tokens = [vocab.go]
    # Deliberately mirrors the pinned VietOCR translate() loop: 129 possible
    # output tokens when max_seq_length=128, terminating early upon EOS.
    for _ in range(info["decoder_max_seq_length"] + 1):
        prefix = np.asarray(tokens, dtype=np.int64).reshape(-1, 1)
        last_logits = dec_session.run(
            ["logits"], {"tokens": prefix, "memory": memory}
        )[0]
        token = int(last_logits[0].argmax())
        tokens.append(token)
        if token == vocab.eos:
            break
    return vocab.decode(tokens), vocab.eos not in tokens


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--reference", type=Path, default=REFERENCE)
    parser.add_argument("--onnx-dir", type=Path, default=OUTPUT)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--weights", type=Path, default=WEIGHTS)
    parser.add_argument("--smoke-lines", type=int, default=0, help="Diagnostic subset (not a passing full parity gate)")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    import onnxruntime as ort
    import run_vietocr
    from PIL import Image
    from bakeoff_common import verified_crop_path

    run_vietocr.check_pinned_checkout()
    sys.dont_write_bytecode = True
    if str(run_vietocr.VIETOCR_DIR) not in sys.path:
        sys.path.insert(0, str(run_vietocr.VIETOCR_DIR))
    from vietocr.model.vocab import Vocab
    rows = read_jsonl(args.manifest)
    validate_manifest(rows)
    expected = verify_reference(rows, args.reference)
    info = verify_onnx_files(args.onnx_dir, args.config, args.weights)
    if args.smoke_lines < 0:
        raise SystemExit("--smoke-lines cannot be negative")
    diagnostic = args.smoke_lines > 0
    subset = rows[:args.smoke_lines] if diagnostic else rows

    encoder = ort.InferenceSession(
        str(args.onnx_dir / "encoder.onnx"), providers=["CPUExecutionProvider"]
    )
    decoder = ort.InferenceSession(
        str(args.onnx_dir / "decoder_step.onnx"), providers=["CPUExecutionProvider"]
    )
    vocab = Vocab(info["vocab"])
    if len(vocab) != info["vocab_size"]:
        raise SystemExit("STOP: frozen vocabulary size does not match ONNX metadata")

    mismatches = []
    decoder_limit_hits = 0
    for count, row in enumerate(subset, 1):
        # verified_crop_path checks the frozen crop SHA256 before inference.
        path = verified_crop_path(row, args.manifest.parent)
        with Image.open(path) as image:
            observed, hit_limit = predict_one(image, encoder, decoder, info, vocab)
        decoder_limit_hits += int(hit_limit)
        reference = expected[row["id"]]
        if observed != reference:
            mismatches.append({
                "id": row["id"], "split": row["split"],
                "expected_pytorch": reference, "observed_onnx": observed,
                "hit_decoder_limit": hit_limit,
            })
            if len(mismatches) <= 10:
                print(f"MISMATCH {row['id']}: PyTorch={reference!r}, ONNX={observed!r}", flush=True)
        if count % 50 == 0 or count == len(subset):
            print(f"processed {count}/{len(subset)}, text mismatches {len(mismatches)}", flush=True)

    passed = not diagnostic and len(subset) == 752 and not mismatches and decoder_limit_hits == 0
    status = "PASS" if passed else "DIAGNOSTIC_ONLY" if diagnostic else "FAIL"
    report = {
        "result": status,
        "selected": info["selected"],
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "onnx_encoder_sha256": info["encoder_sha256"],
        "onnx_decoder_sha256": info["decoder_sha256"],
        "reference_predictions": args.reference.name,
        "manifest": args.manifest.name,
        "scored_non_blind_lines": len(subset),
        "total_non_blind_lines": 752,
        "text_mismatches": len(mismatches),
        "decoder_limit_hits": decoder_limit_hits,
        "mismatch_samples": mismatches[:30],
        "blind_test_used": False,
        "runtime_provider": "CPUExecutionProvider",
        "runtime_version": ort.__version__,
        "deployment_approved": False,
    }
    target = args.report or args.onnx_dir / ("parity_smoke.json" if diagnostic else "parity_full.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ONNX PARITY: {status}; mismatches={len(mismatches)}; decoder limit hits={decoder_limit_hits} -> {target}")
    return 0 if passed or diagnostic else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
r"""Stage NON-BLIND preprocessed tensors and frozen reference text for browser ONNX/WebGPU parity.

Windows CMD:
  .venv-vietocr\Scripts\python.exe datasets\vietnamese_recognition\prepare_vietocr_webgpu_parity.py
  .venv-vietocr\Scripts\python.exe datasets\vietnamese_recognition\prepare_vietocr_webgpu_parity.py --all

The Python runner performs PIL/LANCZOS preprocessing. In-browser code reads the
resulting float32 CHW tensor, not a potentially different Canvas interpolation.
No blind-test crop or blind-test prediction may be accessed.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

import numpy as np

import dataset_common as dataset
from export_vietocr_onnx import CHECKPOINT_SHA256, CONFIG, OUTPUT, WEIGHTS, sha256

REPO = dataset.REPO_ROOT
WEB = REPO / "web/vietocr_onnx_parity"
SAMPLES = WEB / "public/fixtures"
ARTIFACTS = WEB / "public/artifacts"
EVAL_INPUTS = REPO / "eval_inputs.jsonl"
PYTORCH_PREDICTIONS = REPO / "predictions_exp_b_width1024.jsonl"
EXPECTED_SPLITS = {"real_val": 100, "synthetic_val": 552, "bakeoff_regression": 100}


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as reader:
        return [json.loads(row) for row in reader if row.strip()]


def stage(limit: int, all_samples: bool) -> dict:
    import run_vietocr
    from PIL import Image
    from bakeoff_common import verified_crop_path

    run_vietocr.check_pinned_checkout()
    sys.dont_write_bytecode = True
    if str(run_vietocr.VIETOCR_DIR) not in sys.path:
        sys.path.insert(0, str(run_vietocr.VIETOCR_DIR))
    from vietocr.tool.translate import process_input

    parity = json.loads((OUTPUT / "parity_full.json").read_text(encoding="utf-8"))
    if not (
        parity.get("result") == "PASS"
        and parity.get("scored_non_blind_lines") == 752
        and parity.get("text_mismatches") == 0
        and parity.get("blind_test_used") is False
        and parity.get("checkpoint_sha256") == CHECKPOINT_SHA256
    ):
        raise SystemExit("STOP: full 752-line CPU ONNX parity is not PASS")
    meta = json.loads((OUTPUT / "metadata.json").read_text(encoding="utf-8"))
    for key, value in {
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "config_sha256": sha256(CONFIG),
        "encoder_sha256": sha256(OUTPUT / "encoder.onnx"),
        "decoder_sha256": sha256(OUTPUT / "decoder_step.onnx"),
        "image_max_width": 1024,
        "decoder_max_seq_length": 128,
        "batch_size": 1,
    }.items():
        if meta.get(key) != value:
            raise SystemExit(f"STOP: ONNX metadata {key} differs from frozen parity model")
    if sha256(WEIGHTS) != CHECKPOINT_SHA256:
        raise SystemExit("STOP: checkpoint SHA-256 does not match selected B model")
    rows = read_jsonl(EVAL_INPUTS)
    if Counter(row.get("split") for row in rows) != EXPECTED_SPLITS:
        raise SystemExit("STOP: manifest is not exactly the 752 frozen non-blind rows")
    ids = [row["id"] for row in rows]
    if len(set(ids)) != 752:
        raise SystemExit("STOP: manifest IDs are duplicated")
    predictions = read_jsonl(PYTORCH_PREDICTIONS)
    if len(predictions) != 752 or set(row["id"] for row in predictions) != set(ids):
        raise SystemExit("STOP: frozen PyTorch predictions do not match all non-blind IDs")
    ref_meta_path = PYTORCH_PREDICTIONS.with_suffix(".meta.json")
    ref_meta = json.loads(ref_meta_path.read_text(encoding="utf-8"))
    if (
        ref_meta.get("weights_sha256") != CHECKPOINT_SHA256
        or ref_meta.get("image_max_width") != 1024
        or ref_meta.get("decoder_max_seq_length") != 128
    ):
        raise SystemExit("STOP: reference PyTorch metadata differs from frozen B")
    reference = {row["id"]: row["prediction"] for row in predictions}
    if not all_samples and not 1 <= limit <= 752:
        raise SystemExit("STOP: --limit must be 1..752")
    sample_rows = rows if all_samples else rows[:limit]
    # Production artifacts remain outside git; the staging directory has a
    # dedicated .gitignore to prevent accidental checkpoint/eval disclosure.
    SAMPLES.mkdir(parents=True, exist_ok=True)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    for name in ("encoder.onnx", "decoder_step.onnx", "metadata.json"):
        shutil.copy2(OUTPUT / name, ARTIFACTS / name)
    fixtures = []
    for index, row in enumerate(sample_rows):
        path = verified_crop_path(row, EVAL_INPUTS.parent)
        with Image.open(path) as image:
            pixel = process_input(image, 32, 32, 1024).numpy()
        if pixel.shape[:3] != (1, 3, 32) or not 32 <= pixel.shape[3] <= 1024:
            raise SystemExit(f"STOP: unexpected tensor shape {pixel.shape} for {row['id']}")
        filename = f"line_{index:04d}.f32"
        (SAMPLES / filename).write_bytes(pixel.astype("<f4", copy=False).tobytes(order="C"))
        fixtures.append({
            "id": row["id"],
            "split": row["split"],
            "image_file": f"/fixtures/{filename}",
            "image_shape": list(pixel.shape),
            "reference_text": reference[row["id"]],
        })
    manifest = {
        "kind": "FROZEN_NONBLIND_PYTORCH_TO_BROWSER_WEBGPU",
        "total_nonblind_crops": 752,
        "sample_count": len(fixtures),
        "source_checkpoint_sha256": CHECKPOINT_SHA256,
        "encoder_sha256": meta["encoder_sha256"],
        "decoder_sha256": meta["decoder_sha256"],
        "source_full_parity": "PASS",
        "blind_test_used": False,
        "preprocessing": "pinned VietOCR Python PIL/LANCZOS process_input -> little-endian float32 CHW",
        "samples": fixtures,
    }
    (SAMPLES / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"WEBGPU FIXTURES READY: {len(fixtures)}/752 non-blind lines; blind_test_used=false")
    print(f"  Browser test dir: {WEB}")
    print("  Read-only source: frozen PyTorch prediction file; ONNX graphs from approved CPU parity")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--all", action="store_true", help="stage all 752 non-blind crops (potentially large)")
    args = parser.parse_args()
    stage(args.limit, args.all)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

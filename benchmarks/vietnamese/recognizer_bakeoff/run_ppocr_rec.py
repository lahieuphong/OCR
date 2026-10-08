#!/usr/bin/env python3
"""Recognise the exported line crops with PP-OCRv6_medium_rec.

Usage (PaddlePaddle environment, ``.venv``):
    python benchmarks/vietnamese/recognizer_bakeoff/run_ppocr_rec.py

Recognition only: no detector, no document preprocessing, no orientation model.
The input is the crop files listed in ``manifest.jsonl``, the same files
``run_vietocr.py`` reads. Writes ``predictions/ppocrv6.jsonl``.

The model runs with its stock dictionary. Crops go through one at a time, so a
prediction does not depend on which other crops share its batch.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import bakeoff_common as bakeoff

MODEL_NAME = bakeoff.FROZEN_PROFILE.recognition_model


def create_model(device: str):
    from paddleocr import TextRecognition

    return TextRecognition(model_name=MODEL_NAME, device=device)


def recognise(model, image) -> tuple[str, float, float]:
    """Text, score and elapsed milliseconds for one crop."""
    started = time.perf_counter()
    results = list(model.predict(image, batch_size=1))
    elapsed_ms = (time.perf_counter() - started) * 1000
    if len(results) != 1:
        raise RuntimeError(f"expected one result for one crop, got {len(results)}")
    return results[0]["rec_text"], float(results[0]["rec_score"]), elapsed_ms


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=bakeoff.MANIFEST)
    parser.add_argument("--output", type=Path, default=bakeoff.PREDICTION_FILES[bakeoff.PPOCR])
    parser.add_argument("--device", default="cpu")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    import cv2
    import numpy as np

    args = parse_args(argv)
    manifest = bakeoff.load_manifest(args.manifest)
    base_dir = args.manifest.parent

    model = create_model(args.device)
    # The first call pays for graph initialisation; keep it out of the timings.
    recognise(model, np.full((48, 320, 3), 255, dtype=np.uint8))

    rows = []
    for row in manifest:
        # BGR array, the form in which the pipeline passes crops to this model.
        image = cv2.imread(str(bakeoff.verified_crop_path(row, base_dir)), cv2.IMREAD_COLOR)
        text, score, elapsed_ms = recognise(model, image)
        rows.append(
            {
                "id": row["id"],
                "prediction": text,
                "confidence": score,
                "runtime_ms": round(elapsed_ms, 1),
            }
        )

    # How closely recognising the exported crops reproduces what the full
    # pipeline recognised for the same lines. The pipeline batches six crops
    # and pads them to a common width, so a few lines may differ.
    same_as_pipeline = sum(
        row["prediction"] == source["paddle_prediction"] for row, source in zip(rows, manifest)
    )
    total_ms = sum(row["runtime_ms"] for row in rows)
    metadata = {
        "recognizer": MODEL_NAME,
        "character_dictionary": "stock (the model's own inference.yml)",
        "device": args.device,
        "batch_size": 1,
        "paddleocr_version": version("paddleocr"),
        "paddlex_version": version("paddlex"),
        "paddle_version": version("paddlepaddle"),
        "manifest_sha256": bakeoff.sha256_file(args.manifest),
        "crops_processed": len(rows),
        "runtime_seconds": round(total_ms / 1000, 3),
        "mean_runtime_ms": round(total_ms / len(rows), 1) if rows else None,
        "identical_to_pipeline_prediction": same_as_pipeline,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    bakeoff.write_predictions(args.output, rows, metadata)

    print(f"recognizer:      {MODEL_NAME} on {args.device}")
    print(f"crops processed: {len(rows)}")
    print(f"runtime:         {metadata['runtime_seconds']} s ({metadata['mean_runtime_ms']} ms/crop)")
    print(f"same text as the full pipeline: {same_as_pipeline}/{len(rows)}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

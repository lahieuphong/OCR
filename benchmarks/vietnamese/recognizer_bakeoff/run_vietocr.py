#!/usr/bin/env python3
"""Recognise the exported line crops with VietOCR.

Usage (VietOCR environment, ``.venv-vietocr``):
    python benchmarks/vietnamese/recognizer_bakeoff/run_vietocr.py

Recognition only: this script contains no text detection and VietOCR has none.
The input is the crop files listed in ``manifest.jsonl``, the same files
``run_ppocr_rec.py`` reads. Writes ``predictions/vietocr.jsonl``.

VietOCR comes from the pinned submodule ``third_party/vietocr`` and runs in the
configuration its repository recommends for accuracy, ``vgg_transformer``, with
the pretrained weights that configuration names. Three settings are overridden,
none of which changes what the model computes:

    weights          a local copy of the file the configuration points to,
                     checked against a recorded SHA-256
    device           this machine has no CUDA
    cnn.pretrained   false, as in VietOCR's own getting-started notebook: the
                     ImageNet weights it would fetch are overwritten by the
                     checkpoint anyway
"""

from __future__ import annotations

import argparse
import math
import subprocess
import sys
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import bakeoff_common as bakeoff

VIETOCR_DIR = bakeoff.REPO_ROOT / "third_party" / "vietocr"
VIETOCR_COMMIT = "fe8c3a7fc714aec57ab81cec844eb3adf0c1636c"
CONFIG_NAME = "vgg_transformer"
# `Cfg.load_config_from_name` downloads these two files at run time and merges
# them in this order; the copies in the pinned checkout are used instead.
CONFIG_FILES = ("base.yml", "vgg-transformer.yml")
WEIGHTS_PATH = bakeoff.MODELS_DIR / "vietocr" / "vgg_transformer.pth"
WEIGHTS_SHA256 = "380512193a8b6cbf6fad80deacdc9b6939d10d473d199892fc6408d13775ea59"


def check_pinned_checkout() -> None:
    commit = subprocess.run(
        ["git", "-C", str(VIETOCR_DIR), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if commit != VIETOCR_COMMIT:
        raise SystemExit(
            f"third_party/vietocr is at {commit or 'no commit'}, expected {VIETOCR_COMMIT}. "
            "Run `git submodule update --init third_party/vietocr`."
        )


def load_config(weights: Path, device: str):
    import yaml
    from vietocr.tool.config import Cfg

    merged: dict = {}
    for name in CONFIG_FILES:
        with (VIETOCR_DIR / "config" / name).open(encoding="utf-8") as stream:
            merged.update(yaml.safe_load(stream))
    config = Cfg(merged)
    weights_url = config["weights"]
    config["weights"] = str(weights)
    config["device"] = device
    config["cnn"]["pretrained"] = False
    return config, weights_url


def check_weights(path: Path, url: str) -> None:
    if not path.is_file():
        raise SystemExit(f"Missing VietOCR weights: {path}\nDownload {url} to that path.")
    digest = bakeoff.sha256_file(path)
    if digest != WEIGHTS_SHA256:
        raise SystemExit(f"{path} has SHA-256 {digest}, expected {WEIGHTS_SHA256}.")


def recognise(predictor, image) -> tuple[str, float | None, float]:
    """Text, VietOCR's own score (or None) and elapsed milliseconds for one crop."""
    started = time.perf_counter()
    text, probability = predictor.predict(image, return_prob=True)
    elapsed_ms = (time.perf_counter() - started) * 1000
    # The score is the mean probability of the decoded characters. With beam
    # search VietOCR returns none, and for an empty prediction it is 0/0.
    if probability is None or not math.isfinite(float(probability)):
        return text, None, elapsed_ms
    return text, float(probability), elapsed_ms


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=bakeoff.MANIFEST)
    parser.add_argument("--output", type=Path, default=bakeoff.PREDICTION_FILES[bakeoff.VIETOCR])
    parser.add_argument("--weights", type=Path, default=WEIGHTS_PATH)
    parser.add_argument("--device", default="cpu", choices=("cpu", "mps"))
    parser.add_argument(
        "--image-max-width",
        type=int,
        default=None,
        help="Diagnostic only: override the configuration's image_max_width. "
        "Requires --output, so the stock predictions are never replaced by it.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    default_output = bakeoff.PREDICTION_FILES[bakeoff.VIETOCR]
    if args.image_max_width is not None and args.output == default_output:
        raise SystemExit("--image-max-width is a diagnostic: give it its own --output.")

    check_pinned_checkout()
    # Keep the pinned checkout free of bytecode files.
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(VIETOCR_DIR))
    import torch
    from PIL import Image
    from vietocr.tool.predictor import Predictor

    config, weights_url = load_config(args.weights, args.device)
    check_weights(args.weights, weights_url)
    if args.image_max_width is not None:
        config["dataset"]["image_max_width"] = args.image_max_width

    manifest = bakeoff.load_manifest(args.manifest)
    base_dir = args.manifest.parent
    predictor = Predictor(config)
    # The first call pays for one-off initialisation; keep it out of the timings.
    recognise(predictor, Image.new("RGB", (320, 32), "white"))

    rows = []
    for row in manifest:
        with Image.open(bakeoff.verified_crop_path(row, base_dir)) as image:
            text, confidence, elapsed_ms = recognise(predictor, image)
        rows.append(
            {
                "id": row["id"],
                "prediction": text,
                "confidence": confidence,
                "runtime_ms": round(elapsed_ms, 1),
            }
        )

    dataset = config["dataset"]
    # Crops wider than this are squeezed horizontally by VietOCR's own resize.
    widest_ratio = dataset["image_max_width"] / dataset["image_height"]
    squeezed = sum(row["crop_width"] / row["crop_height"] > widest_ratio for row in manifest)
    total_ms = sum(row["runtime_ms"] for row in rows)
    metadata = {
        "recognizer": f"VietOCR {CONFIG_NAME}",
        "repository": "https://github.com/pbcquoc/vietocr",
        "repository_commit": VIETOCR_COMMIT,
        "config_files": [f"third_party/vietocr/config/{name}" for name in CONFIG_FILES],
        "backbone": config["backbone"],
        "seq_modeling": config["seq_modeling"],
        "beamsearch": config["predictor"]["beamsearch"],
        "image_height": dataset["image_height"],
        "image_min_width": dataset["image_min_width"],
        "image_max_width": dataset["image_max_width"],
        "image_max_width_overridden": args.image_max_width is not None,
        "crops_squeezed_to_max_width": squeezed,
        "weights_url": weights_url,
        "weights_sha256": WEIGHTS_SHA256,
        "confidence": "mean softmax probability of the decoded characters, from "
        "Predictor.predict(return_prob=True); not calibrated and not comparable "
        "with the PP-OCRv6 score",
        "device": args.device,
        "batch_size": 1,
        "torch_version": torch.__version__,
        "torchvision_version": version("torchvision"),
        "manifest_sha256": bakeoff.sha256_file(args.manifest),
        "crops_processed": len(rows),
        "runtime_seconds": round(total_ms / 1000, 3),
        "mean_runtime_ms": round(total_ms / len(rows), 1) if rows else None,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    bakeoff.write_predictions(args.output, rows, metadata)

    print(f"recognizer:      VietOCR {CONFIG_NAME} @ {VIETOCR_COMMIT[:10]} on {args.device}")
    print(f"crops processed: {len(rows)}")
    print(f"runtime:         {metadata['runtime_seconds']} s ({metadata['mean_runtime_ms']} ms/crop)")
    print(
        f"crops squeezed to {dataset['image_max_width']} px by VietOCR's resize: "
        f"{squeezed}/{len(rows)}"
    )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

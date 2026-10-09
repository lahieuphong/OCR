#!/usr/bin/env python3
"""Recognise the exported line crops with VietOCR.

Usage (VietOCR environment, ``.venv-vietocr``):
    python benchmarks/vietnamese/recognizer_bakeoff/run_vietocr.py
    python benchmarks/vietnamese/recognizer_bakeoff/run_vietocr.py \
        --config configs/vietnamese/vietocr/exp_a_width512.yml \
        --manifest <inputs.jsonl> --output <predictions.jsonl>

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

How long a line the decoder may write is not left to VietOCR's default. Its
``translate`` stops after ``max_seq_length`` steps, 128 unless told otherwise,
and ``Predictor.predict`` never tells it. This script calls ``translate``
itself and always passes the number:

    without --config   128, VietOCR's default, which is what the bake-off ran
                       with; the stock predictions stay reproducible
    with --config      ``decoder_max_seq_length`` of that project config, and
                       its image widths

Each prediction records whether the decoder ran out of steps before writing
its end token (``hit_decoder_limit``): such a text may be cut short. Nothing in
``third_party/vietocr`` is edited or patched.
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
# Key of a project config (configs/vietnamese/vietocr/exp_*.yml). VietOCR does
# not read it; this script does.
DECODER_KEY = "decoder_max_seq_length"
# What `vietocr.tool.translate.translate` uses when it is not given a number.
STOCK_DECODER_MAX_SEQ_LENGTH = 128


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


def decoder_limit(config: dict, override: int | None = None) -> tuple[int, str]:
    """Decoding steps to allow, and where that number comes from."""
    if override is not None:
        return override, "command line"
    if DECODER_KEY in config:
        return int(config[DECODER_KEY]), "config"
    return STOCK_DECODER_MAX_SEQ_LENGTH, "VietOCR default"


def decodable_characters(max_seq_length: int) -> int:
    """Longest text ``translate`` can write and still close with its end token.

    Its loop runs while ``steps <= max_seq_length``: ``max_seq_length + 1``
    tokens, the last of which has to be the end token.
    """
    return max_seq_length


def load_config(weights: Path, device: str, project_config: Path | None = None):
    import yaml
    from vietocr.tool.config import Cfg

    merged: dict = {}
    for name in CONFIG_FILES:
        with (VIETOCR_DIR / "config" / name).open(encoding="utf-8") as stream:
            merged.update(yaml.safe_load(stream))
    weights_url = merged["weights"]
    if project_config is not None:
        # A project config is the stock one with overrides applied: it stands alone.
        with project_config.open(encoding="utf-8") as stream:
            merged = yaml.safe_load(stream)
        if DECODER_KEY not in merged:
            raise SystemExit(f"{project_config} sets no {DECODER_KEY}.")
    config = Cfg(merged)
    config["weights"] = str(weights)
    config["device"] = device
    config["cnn"]["pretrained"] = False
    return config, weights_url


def check_weights(path: Path, url: str) -> str:
    """SHA-256 of the weights file, after checking it is what it should be.

    The pretrained checkpoint has to be the recorded file. Any other file is
    fine-tuned weights written by ``train_vietocr.py``: it only has to exist,
    and its digest goes into the metadata of the predictions.
    """
    if not path.is_file():
        raise SystemExit(f"Missing VietOCR weights: {path}\nDownload {url} to that path.")
    digest = bakeoff.sha256_file(path)
    if path.resolve() == WEIGHTS_PATH.resolve() and digest != WEIGHTS_SHA256:
        raise SystemExit(f"{path} has SHA-256 {digest}, expected {WEIGHTS_SHA256}.")
    return digest


def recognise(predictor, image, max_seq_length: int) -> tuple[str, float | None, float, bool | None]:
    """Text, VietOCR's own score (or None), elapsed milliseconds, and whether decoding ran out of steps.

    The steps of ``Predictor.predict``, with the one thing it leaves to a
    default passed explicitly: how many tokens the decoder may write.
    """
    from vietocr.tool.translate import process_input, translate, translate_beam_search

    config = predictor.config
    sizes = config["dataset"]
    started = time.perf_counter()
    tensor = process_input(image, sizes["image_height"], sizes["image_min_width"], sizes["image_max_width"])
    tensor = tensor.to(config["device"])
    if config["predictor"]["beamsearch"]:
        tokens = translate_beam_search(tensor, predictor.model, max_seq_length=max_seq_length)
        probability, hit_limit = None, None  # beam search reports neither
    else:
        sentences, probabilities = translate(tensor, predictor.model, max_seq_length=max_seq_length)
        tokens, probability = sentences[0].tolist(), probabilities[0]
        # No end token: the decoder stopped because it ran out of steps.
        hit_limit = predictor.vocab.eos not in tokens
    text = predictor.vocab.decode(tokens)
    elapsed_ms = (time.perf_counter() - started) * 1000
    # The score is the mean probability of the decoded characters. With beam
    # search VietOCR returns none, and for an empty prediction it is 0/0.
    if probability is None or not math.isfinite(float(probability)):
        return text, None, elapsed_ms, hit_limit
    return text, float(probability), elapsed_ms, hit_limit


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=bakeoff.MANIFEST)
    parser.add_argument("--output", type=Path, default=bakeoff.PREDICTION_FILES[bakeoff.VIETOCR])
    parser.add_argument("--weights", type=Path, default=WEIGHTS_PATH)
    parser.add_argument("--device", default="cpu", help="cpu (default), mps, or a CUDA device such as cuda:0.")
    parser.add_argument(
        "--image-max-width",
        type=int,
        default=None,
        help="Diagnostic only: override the configuration's image_max_width. "
        "Requires --output, so the stock predictions are never replaced by it.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="A project config (configs/vietnamese/vietocr/exp_*.yml): its image widths and its "
        f"{DECODER_KEY} are used instead of the stock ones. Requires --output.",
    )
    parser.add_argument(
        "--decoder-max-seq-length",
        type=int,
        default=None,
        help="Diagnostic only: decoding steps to allow, whatever the configuration says. Requires --output.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    default_output = bakeoff.PREDICTION_FILES[bakeoff.VIETOCR]
    if args.image_max_width is not None and args.output == default_output:
        raise SystemExit("--image-max-width is a diagnostic: give it its own --output.")
    if (args.config is not None or args.decoder_max_seq_length is not None) and args.output == default_output:
        raise SystemExit("--config and --decoder-max-seq-length need their own --output: the stock predictions stay as they are.")
    if args.decoder_max_seq_length is not None and args.decoder_max_seq_length < 1:
        raise SystemExit("--decoder-max-seq-length must be at least 1.")

    check_pinned_checkout()
    # Keep the pinned checkout free of bytecode files.
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(VIETOCR_DIR))
    import torch
    from PIL import Image
    from vietocr.tool.predictor import Predictor

    config, weights_url = load_config(args.weights, args.device, args.config)
    weights_sha256 = check_weights(args.weights, weights_url)
    pretrained = weights_sha256 == WEIGHTS_SHA256
    if not pretrained and args.config is None:
        raise SystemExit("Fine-tuned weights are read with the config they were trained with: pass --config.")
    if args.image_max_width is not None:
        config["dataset"]["image_max_width"] = args.image_max_width
    max_seq_length, limit_source = decoder_limit(config, args.decoder_max_seq_length)
    if max_seq_length + 1 > config["transformer"]["max_seq_length"]:
        raise SystemExit(
            f"{max_seq_length} decoding steps need {max_seq_length + 1} positions; the model has "
            f"{config['transformer']['max_seq_length']} (transformer.max_seq_length)."
        )

    manifest = bakeoff.load_manifest(args.manifest)
    base_dir = args.manifest.parent
    predictor = Predictor(config)
    # The first call pays for one-off initialisation; keep it out of the timings.
    recognise(predictor, Image.new("RGB", (320, 32), "white"), max_seq_length)

    rows = []
    for row in manifest:
        with Image.open(bakeoff.verified_crop_path(row, base_dir)) as image:
            text, confidence, elapsed_ms, hit_limit = recognise(predictor, image, max_seq_length)
        rows.append(
            {
                "id": row["id"],
                "prediction": text,
                "confidence": confidence,
                "runtime_ms": round(elapsed_ms, 1),
                "hit_decoder_limit": hit_limit,
            }
        )

    dataset = config["dataset"]
    # Crops wider than this are squeezed horizontally by VietOCR's own resize.
    widest_ratio = dataset["image_max_width"] / dataset["image_height"]
    squeezed = sum(row["crop_width"] / row["crop_height"] > widest_ratio for row in manifest)
    total_ms = sum(row["runtime_ms"] for row in rows)
    at_limit = sum(row["hit_decoder_limit"] is True for row in rows)
    metadata = {
        "recognizer": f"VietOCR {CONFIG_NAME}",
        "repository": "https://github.com/pbcquoc/vietocr",
        "repository_commit": VIETOCR_COMMIT,
        "config_files": [f"third_party/vietocr/config/{name}" for name in CONFIG_FILES],
        "project_config": args.config.name if args.config is not None else None,
        "decoder_max_seq_length": max_seq_length,
        "decoder_max_seq_length_source": limit_source,
        "longest_text_with_end_token": decodable_characters(max_seq_length),
        "predictions_at_decoder_limit": at_limit,
        "backbone": config["backbone"],
        "seq_modeling": config["seq_modeling"],
        "beamsearch": config["predictor"]["beamsearch"],
        "image_height": dataset["image_height"],
        "image_min_width": dataset["image_min_width"],
        "image_max_width": dataset["image_max_width"],
        "image_max_width_overridden": args.image_max_width is not None,
        "crops_squeezed_to_max_width": squeezed,
        "weights_url": weights_url if pretrained else None,
        "weights_file": args.weights.name,
        "weights_sha256": weights_sha256,
        "weights_are_the_pretrained_checkpoint": pretrained,
        "confidence": "mean softmax probability of the decoded characters, as "
        "Predictor.predict(return_prob=True) computes it; not calibrated and not "
        "comparable with the PP-OCRv6 score",
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
    print(f"weights:         {'pretrained' if pretrained else 'fine-tuned'} {args.weights.name} ({weights_sha256[:12]})")
    print(f"crops processed: {len(rows)}")
    print(f"runtime:         {metadata['runtime_seconds']} s ({metadata['mean_runtime_ms']} ms/crop)")
    print(
        f"crops squeezed to {dataset['image_max_width']} px by VietOCR's resize: "
        f"{squeezed}/{len(rows)}"
    )
    print(f"decoder steps:   {max_seq_length} ({limit_source}); predictions that ran out of steps: {at_limit}/{len(rows)}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

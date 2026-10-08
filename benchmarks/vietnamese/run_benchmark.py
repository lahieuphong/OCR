#!/usr/bin/env python3
"""Run one benchmark profile of the PP-OCRv6 Vietnamese baseline.

Usage:
    python benchmarks/vietnamese/run_benchmark.py \
        --input experiments/vietnamese_baseline/input \
        --profile ppocrv6_vi_unwarp_on

The OCR itself is done by ``experiments/vietnamese_baseline/run_ocr.py``; this
script only maps a profile to that script's options and gives every profile its
own output directory, ``<output-root>/<profile>/<document>/``.

Run profiles one after the other, not in parallel: each run loads its own copy
of the models.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common import BASELINE_DIR, OUTPUT_ROOT, PROFILES, Profile

sys.path.insert(0, str(BASELINE_DIR))
import run_ocr  # noqa: E402


def check_profile_matches_baseline(profile: Profile) -> None:
    """The profile's models must be the ones the baseline script is locked to."""
    declared = (
        profile.lang,
        profile.ocr_version,
        profile.detection_model,
        profile.recognition_model,
    )
    baseline = (
        run_ocr.LANG,
        run_ocr.OCR_VERSION,
        run_ocr.DETECTION_MODEL,
        run_ocr.RECOGNITION_MODEL,
    )
    if declared != baseline:
        raise SystemExit(
            f"Profile {profile.name} declares {declared}, but run_ocr.py runs {baseline}."
        )


def baseline_arguments(
    profile: Profile, input_path: Path, output_root: Path, device: str
) -> list[str]:
    def flag(value: bool) -> str:
        return "true" if value else "false"

    return [
        "--input", str(input_path),
        "--output", str(output_root / profile.name),
        "--device", device,
        "--profile", profile.name,
        "--use-doc-orientation", flag(profile.use_doc_orientation_classify),
        "--use-doc-unwarping", flag(profile.use_doc_unwarping),
        "--use-textline-orientation", flag(profile.use_textline_orientation),
    ]  # fmt: skip


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--profile", required=True, choices=sorted(PROFILES))
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    profile = PROFILES[args.profile]
    check_profile_matches_baseline(profile)
    return run_ocr.main(
        baseline_arguments(profile, args.input, args.output_root, args.device)
    )


if __name__ == "__main__":
    sys.exit(main())

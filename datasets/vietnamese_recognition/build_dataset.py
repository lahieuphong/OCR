#!/usr/bin/env python3
"""Build the pilot recognition dataset.

Usage:
    python datasets/vietnamese_recognition/build_dataset.py

Writes, under this directory:

    train/images/, train/clean/      augmented and clean synthetic line images
    val/images/, val/clean/
    manifests/train.tsv, val.tsv     canonical manifests
    manifests/test.tsv               the frozen holdout in the same schema
    manifests/vietocr/*.txt          the same splits as VietOCR annotation files
    manifests/build_report.json      what was built, from which seeds and fonts

Training and validation are made of:

    synthetic   lines from text_generator.py, including a long-line subset
    hard_case   synthetic lines containing an entry of manifests/hard_cases.txt
    real        crops a person verified in real_annotation/ (none until then)

The frozen test lines are never written to train or validation: not their
ids, not their images, and by default not even a synthetic line with the same
text. Validation uses its own seed and shares no text with training.

Everything is reproducible: the same seeds, fonts and library versions give
the same files. The build stops if the result would break one of these rules.
"""

from __future__ import annotations

import argparse
import itertools
import os
import random
import shutil
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path

import dataset_common as dataset
from dataset_common import HARD_CASE, LONG_LINE, REAL, SYNTHETIC, TEST, TRAIN, VAL

import bakeoff_common as bakeoff  # noqa: E402  (path set up by dataset_common)
from audit_charset import vietnamese_letters  # noqa: E402
from evaluate_recognizers import usable_rows  # noqa: E402

DATASET_NAME = "pilot-v1"
COVERAGE = "coverage"


@dataclass(frozen=True)
class SplitSpec:
    seed: int
    synthetic: int  # ordinary lines
    long_lines: int  # lines longer than the recognizer's usual width
    per_hard_case: int  # lines per entry of hard_cases.txt
    min_letter_occurrences: int  # of every Vietnamese letter, in the split


# A pilot sized for a laptop. Training and validation have different seeds.
PILOT = {
    TRAIN: SplitSpec(seed=20261101, synthetic=3000, long_lines=1000, per_hard_case=12, min_letter_occurrences=30),
    VAL: SplitSpec(seed=20261102, synthetic=300, long_lines=100, per_hard_case=2, min_letter_occurrences=3),
}


def recognizer_vocabulary() -> str:
    """Characters the pretrained VietOCR model can output, from the pinned config."""
    import yaml

    with (dataset.VIETOCR_DIR / "config" / "base.yml").open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)["vocab"]


def unique_line(make, seen: set[str], *seed_parts: object):
    """The first line from ``make`` that is not in ``seen``; reseeded per attempt."""
    for attempt in itertools.count():
        if attempt > 500:
            raise RuntimeError(f"no new line after 500 attempts for {seed_parts}")
        line = make(random.Random(":".join(map(str, (*seed_parts, attempt)))))
        if line.text not in seen:
            seen.add(line.text)
            return line


def split_texts(generator, spec: SplitSpec, split: str, hard_cases: list[str], seen: set[str]) -> list[dict]:
    """Every synthetic sample of one split, as ``{id, text, kind, source_type, subset}``."""
    samples = []
    numbering: Counter = Counter()

    def add(prefix: str, line, source_type: str, subset: str = "") -> None:
        numbering[prefix] += 1
        samples.append(
            {
                "id": f"{prefix}_{split}_{numbering[prefix]:06d}",
                "text": line.text,
                "kind": line.kind,
                "source_type": source_type,
                "subset": subset,
            }
        )

    for index in range(spec.synthetic):
        add("syn", unique_line(generator.line, seen, spec.seed, "line", index), SYNTHETIC)
    for index in range(spec.long_lines):
        make = lambda rng: generator.line(rng, long=True)  # noqa: E731
        add("long", unique_line(make, seen, spec.seed, "long", index), SYNTHETIC, LONG_LINE)
    for phrase in hard_cases:
        for index in range(spec.per_hard_case):
            make = lambda rng, phrase=phrase: generator.hard_case_line(rng, phrase, seen)  # noqa: E731
            add("hard", unique_line(make, seen, spec.seed, "hard", phrase, index), HARD_CASE)

    # Top up until every Vietnamese letter is frequent enough to be learnt.
    letters = vietnamese_letters()
    counts = Counter(character for sample in samples for character in sample["text"])
    for round_number in itertools.count():
        rarest = min(letters, key=lambda letter: counts[letter])
        if counts[rarest] >= spec.min_letter_occurrences:
            break
        make = lambda rng, letter=rarest: generator.coverage_line(rng, letter)  # noqa: E731
        line = unique_line(make, seen, spec.seed, "coverage", rarest, round_number)
        counts.update(line.text)
        add("cov", line, SYNTHETIC, COVERAGE)
    return samples


def render_split(samples: list[dict], split: str, seed: int, fonts: list, root: Path) -> list[dict]:
    """Write the clean and augmented image of each sample; return manifest rows."""
    import cv2

    from render import render

    for folder in ("images", "clean"):
        shutil.rmtree(root / split / folder, ignore_errors=True)
        (root / split / folder).mkdir(parents=True)
    rows = []
    for sample in samples:
        rendered = render(sample["text"], sample["kind"], fonts, seed, sample["id"])
        image_path = Path(split) / "images" / f"{sample['id']}.png"
        clean_path = Path(split) / "clean" / f"{sample['id']}.png"
        if not cv2.imwrite(str(root / image_path), rendered.augmented) or not cv2.imwrite(
            str(root / clean_path), rendered.clean
        ):
            raise SystemExit(f"Cannot write the images of {sample['id']}.")
        rows.append(
            dataset.manifest_row(
                id=sample["id"],
                source_document=f"synthetic/{DATASET_NAME}",
                image_path=image_path.as_posix(),
                text=sample["text"],
                split=split,
                source_type=sample["source_type"],
                verified="true",  # the label is the text that was rendered
                crop_sha256=dataset.sha256_file(root / image_path),
                image_width=rendered.augmented.shape[1],
                image_height=rendered.augmented.shape[0],
                subset=sample["subset"],
                font=rendered.font,
                clean_image_path=clean_path.as_posix(),
            )
        )
    return rows


def real_rows(holdout: dataset.Holdout, annotation_dir: Path, root: Path) -> tuple[list[dict], dict]:
    """Human-verified real lines for training, grouped so a page stays in one split.

    Only rows a person verified are taken, never a prediction. Lines of the
    frozen test set are refused by id, by image and by text.
    """
    table = annotation_dir / bakeoff.ANNOTATION_MANIFEST.name
    report = {"verified": 0, "refused_as_test": 0}
    if not table.is_file() or not bakeoff.MANIFEST.is_file():
        return [], report
    crops = {row["id"]: row for row in bakeoff.load_manifest()}
    verified, _ = usable_rows(bakeoff.read_annotation(table))
    kept = []
    for row in verified:
        crop = crops[row["id"]]
        text = dataset.nfc(row["ground_truth"])
        if row["id"] in holdout.ids or crop["crop_sha256"] in holdout.hashes or text in holdout.texts:
            report["refused_as_test"] += 1
            continue
        kept.append((row, crop, text))
    report["verified"] = len(kept)

    # Whole pages go to one split: every fifth page (in sorted order) validates.
    groups = sorted({(row["document"], int(row["page"])) for row, _, _ in kept})
    validation = {group for index, group in enumerate(groups) if index % 5 == 4}
    rows = []
    for row, crop, text in kept:
        path = bakeoff.BAKEOFF_DIR / crop["crop_path"]
        rows.append(
            dataset.manifest_row(
                id=row["id"],
                source_document=row["document"],
                page=row["page"],
                line_index=crop["line_index"],
                image_path=Path(os.path.relpath(path, root)).as_posix(),
                text=text,
                split=VAL if (row["document"], int(row["page"])) in validation else TRAIN,
                source_type=REAL,
                verified="true",
                crop_sha256=crop["crop_sha256"],
                image_width=crop["crop_width"],
                image_height=crop["crop_height"],
            )
        )
    return rows, report


def holdout_as_manifest(holdout: dataset.Holdout, root: Path) -> list[dict]:
    """The frozen holdout in the canonical schema."""
    crops = {row["id"]: row for row in bakeoff.load_manifest()} if bakeoff.MANIFEST.is_file() else {}
    rows = []
    for row in holdout.rows:
        crop = crops.get(row["id"], {})
        path = bakeoff.BAKEOFF_DIR / "crops" / f"{row['id']}.png"
        rows.append(
            dataset.manifest_row(
                id=row["id"],
                source_document=row["document"],
                page=row["page"],
                line_index=row["line_index"],
                image_path=Path(os.path.relpath(path, root)).as_posix(),
                text=row["ground_truth"],
                split=TEST,
                source_type=REAL,
                verified="true",
                crop_sha256=row["crop_sha256"],
                image_width=crop.get("crop_width", ""),
                image_height=crop.get("crop_height", ""),
            )
        )
    return rows


def write_vietocr_annotations(root: Path, splits: dict[str, list[dict]]) -> None:
    """One ``image path<TAB>label`` line per sample, the format VietOCR trains from."""
    for split, rows in splits.items():
        text = "".join(f"{row['image_path']}\t{row['text']}\n" for row in rows)
        dataset.write_text_atomic(root / "manifests" / "vietocr" / f"{split}_annotation.txt", text)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=dataset.DATASET_DIR, help="Where train/, val/ and manifests/ go.")
    parser.add_argument("--hard-cases", type=Path, default=dataset.HARD_CASES)
    parser.add_argument("--real-annotation-dir", type=Path, default=dataset.REAL_ANNOTATION_DIR)
    parser.add_argument("--scale", type=float, default=1.0, help="Multiply every sample count (for a quick trial).")
    parser.add_argument(
        "--allow-test-texts",
        action="store_true",
        help="Let synthetic lines repeat the text of a frozen test line (off by default).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from fonts import SERIF, discover
    from text_generator import Lexicon, TextGenerator, load_hard_cases

    args = parse_args(argv)
    started = time.time()
    holdout = dataset.Holdout.load()
    vocabulary = recognizer_vocabulary()
    fonts, rejected_fonts = discover(vocabulary)
    if not any(font.category == SERIF for font in fonts):
        raise SystemExit("No Times-like font with full Vietnamese coverage was found on this system.")
    banned = frozenset() if args.allow_test_texts else frozenset(holdout.texts)
    generator = TextGenerator(Lexicon(), vocabulary, banned)
    hard_cases = load_hard_cases(args.hard_cases)

    specs = {
        split: SplitSpec(
            spec.seed,
            max(1, round(spec.synthetic * args.scale)),
            max(1, round(spec.long_lines * args.scale)),
            max(1, round(spec.per_hard_case * args.scale)),
            max(1, round(spec.min_letter_occurrences * args.scale)),
        )
        for split, spec in PILOT.items()
    }
    seen: set[str] = set()
    splits: dict[str, list[dict]] = {}
    for split in (TRAIN, VAL):  # validation second, so it avoids every training text
        samples = split_texts(generator, specs[split], split, hard_cases, seen)
        splits[split] = render_split(samples, split, specs[split].seed, fonts, args.root)
        print(f"{split}: rendered {len(splits[split])} synthetic lines")

    real, real_report = real_rows(holdout, args.real_annotation_dir, args.root)
    for row in real:
        splits[row["split"]].append(row)
    splits[TEST] = holdout_as_manifest(holdout, args.root)

    # The rules, checked on what is about to be written.
    problems = holdout.leaks(splits[TRAIN] + splits[VAL])
    train_texts = {row["text"] for row in splits[TRAIN]}
    problems += [f"{row['id']}: text also in training" for row in splits[VAL] if row["text"] in train_texts]
    if not args.allow_test_texts:
        problems += [
            f"{row['id']}: text of a frozen test line"
            for row in splits[TRAIN] + splits[VAL]
            if row["text"] in holdout.texts
        ]
    if problems:
        raise SystemExit("Build refused:\n  " + "\n  ".join(problems[:20]))

    for split, rows in splits.items():
        dataset.write_manifest(args.root / "manifests" / f"{split}.tsv", rows)
    write_vietocr_annotations(args.root, splits)

    import cv2
    import numpy

    bakeoff.write_json(
        args.root / "manifests" / "build_report.json",
        {
            "dataset": DATASET_NAME,
            "specification": {split: asdict(spec) for split, spec in specs.items()},
            "samples": {
                split: dict(Counter(f"{row['source_type']}/{row['subset'] or 'general'}" for row in rows))
                for split, rows in splits.items()
            },
            "real_lines": real_report,
            "synthetic_may_repeat_test_texts": args.allow_test_texts,
            "hard_cases": len(hard_cases),
            "fonts_accepted": sorted(font.name for font in fonts),
            "fonts_rejected": rejected_fonts,
            "fonts_used": dict(Counter(row["font"] for row in splits[TRAIN] + splits[VAL] if row["font"])),
            "libraries": {"pillow": version("pillow"), "opencv": cv2.__version__, "numpy": numpy.__version__},
            "seconds": round(time.time() - started, 1),
        },
    )
    for split in (TRAIN, VAL, TEST):
        kinds = Counter(row["source_type"] for row in splits[split])
        print(f"{split}: {len(splits[split])} lines {dict(kinds)}")
    print(f"real lines verified for training: {real_report['verified']}")
    print(f"wrote manifests and VietOCR annotation files under {args.root / 'manifests'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

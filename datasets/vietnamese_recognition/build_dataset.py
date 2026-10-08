#!/usr/bin/env python3
"""Build the manifests of the recognition dataset.

Usage:
    python datasets/vietnamese_recognition/build_dataset.py
    python datasets/vietnamese_recognition/build_dataset.py --skip-synthetic   # real lines changed only

The dataset has six sets, one manifest each under ``manifests/``:

    real_train           verified lines of the documents assigned to train
    real_val             verified lines of the documents assigned to val
    synthetic_train      generated lines, including long lines and hard cases
    synthetic_val        generated with another seed, sharing no text with training
    bakeoff_regression   the 100 frozen lines the recognizer was chosen on
    blind_test           verified lines of the documents assigned to blind

A real line enters a set only after a person verified it, and always the set
of its document. A document never has lines in two sets. No frozen bake-off
line is written to another set: not its id, not its image, and by default not
even a synthetic line with the same text.

The training pass a recognizer sees is a mix of ``real_train`` and
``synthetic_train`` controlled by ``configs/vietnamese/vietocr/data_mix.yml``;
the mix is written to ``manifests/vietocr/train_mix_annotation.txt`` and can
be changed and rebuilt at any time.

The build stops, writing nothing, if the result would break one of the rules.
"""

from __future__ import annotations

import argparse
import itertools
import json
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
from dataset_common import (
    BAKEOFF_REGRESSION,
    BLIND_TEST,
    HARD_CASE,
    LEARNING_SPLITS,
    LONG_LINE,
    REAL,
    REAL_TRAIN,
    REAL_VAL,
    SYNTHETIC,
    SYNTHETIC_TRAIN,
    SYNTHETIC_VAL,
)

import bakeoff_common as bakeoff  # noqa: E402  (path set up by dataset_common)
from audit_charset import vietnamese_letters  # noqa: E402
from evaluate_recognizers import usable_rows  # noqa: E402

DATASET_NAME = "pilot-v1"
COVERAGE = "coverage"
# A real line with a character the recognizer has no class for. It is kept in
# its manifest and scored as it is, but VietOCR cannot be trained on it.
OUT_OF_VOCABULARY = "out_of_vocabulary"
MIX_CONFIG = dataset.VIETOCR_CONFIG_DIR / "data_mix.yml"
TRAIN_MIX = "train_mix"
MIX_METHODS = ("oversample_real", "subsample_synthetic")
GENERATION_KEYS = ("specification", "hard_cases", "fonts_accepted", "fonts_rejected", "libraries")


@dataclass(frozen=True)
class SplitSpec:
    folder: str  # where the images go, and the name used in sample ids
    seed: int
    synthetic: int  # ordinary lines
    long_lines: int  # lines longer than the recognizer's usual width
    per_hard_case: int  # lines per entry of hard_cases.txt
    min_letter_occurrences: int  # of every Vietnamese letter, in the set


# A pilot sized for a laptop. Training and validation have different seeds.
PILOT = {
    SYNTHETIC_TRAIN: SplitSpec("train", 20261101, synthetic=3000, long_lines=1000, per_hard_case=12, min_letter_occurrences=30),
    SYNTHETIC_VAL: SplitSpec("val", 20261102, synthetic=300, long_lines=100, per_hard_case=2, min_letter_occurrences=3),
}


def recognizer_vocabulary() -> str:
    """Characters the pretrained VietOCR model can output, from the pinned config."""
    import yaml

    with (dataset.VIETOCR_DIR / "config" / "base.yml").open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)["vocab"]


# --- synthetic lines -----------------------------------------------------------


def unique_line(make, seen: set[str], *seed_parts: object):
    """The first line from ``make`` that is not in ``seen``; reseeded per attempt."""
    for attempt in itertools.count():
        if attempt > 500:
            raise RuntimeError(f"no new line after 500 attempts for {seed_parts}")
        line = make(random.Random(":".join(map(str, (*seed_parts, attempt)))))
        if line.text not in seen:
            seen.add(line.text)
            return line


def split_texts(generator, spec: SplitSpec, hard_cases: list[str], seen: set[str]) -> list[dict]:
    """Every synthetic sample of one set, as ``{id, text, kind, source_type, subset}``."""
    samples = []
    numbering: Counter = Counter()

    def add(prefix: str, line, source_type: str, subset: str = "") -> None:
        numbering[prefix] += 1
        samples.append(
            {
                "id": f"{prefix}_{spec.folder}_{numbering[prefix]:06d}",
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


def render_split(samples: list[dict], split: str, spec: SplitSpec, fonts: list, root: Path) -> list[dict]:
    """Write the clean and augmented image of each sample; return manifest rows."""
    import cv2

    from render import render

    for folder in ("images", "clean"):
        shutil.rmtree(root / spec.folder / folder, ignore_errors=True)
        (root / spec.folder / folder).mkdir(parents=True)
    rows = []
    for sample in samples:
        rendered = render(sample["text"], sample["kind"], fonts, spec.seed, sample["id"])
        image_path = Path(spec.folder) / "images" / f"{sample['id']}.png"
        clean_path = Path(spec.folder) / "clean" / f"{sample['id']}.png"
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


# --- real lines ----------------------------------------------------------------


def real_rows(documents: list[dict], work_dir: Path, root: Path, frozen_blind: list[dict] | None) -> dict[str, list[dict]]:
    """Human-verified lines of the new documents, each in the set of its document.

    Only rows a person verified are taken, never a prediction. A verified line
    found in the table of a set its document does not belong to stops the
    build: that is a document leaking across sets.
    """
    result: dict[str, list[dict]] = {REAL_TRAIN: [], REAL_VAL: [], BLIND_TEST: []}
    lines_path = work_dir / "manifest.jsonl"
    if not lines_path.is_file():
        return result
    crops = {row["id"]: row for row in bakeoff.load_manifest(lines_path)}
    assigned = {d["document_id"]: dataset.DOCUMENT_SPLITS.get(d["split"]) for d in documents}

    def row_for(split: str, identifier: str, text: str) -> dict:
        crop = crops[identifier]
        if assigned.get(crop["document_id"]) != split:
            raise SystemExit(
                f"Build refused: {identifier} is a {split} line, but its document {crop['document_id']} "
                f"is assigned to {assigned.get(crop['document_id']) or 'no set'}."
            )
        return dataset.manifest_row(
            id=identifier,
            source_document=crop["document_id"],
            page=crop["page"],
            line_index=crop["line_index"],
            image_path=Path(os.path.relpath(work_dir / crop["crop_path"], root)).as_posix(),
            text=dataset.nfc(text),
            split=split,
            source_type=REAL,
            verified="true",
            crop_sha256=crop["crop_sha256"],
            image_width=crop["crop_width"],
            image_height=crop["crop_height"],
        )

    for split in result:
        if split == BLIND_TEST and frozen_blind is not None:
            # Once frozen, the blind test is what the frozen file says.
            result[split] = [row_for(split, row["id"], row["ground_truth"]) for row in frozen_blind]
            continue
        table = work_dir / "annotation" / split / bakeoff.ANNOTATION_MANIFEST.name
        if table.is_file():
            verified, _ = usable_rows(bakeoff.read_annotation(table))
            result[split] = [row_for(split, row["id"], row["ground_truth"]) for row in verified]
    return result


def regression_rows(frozen: dataset.FrozenLines, root: Path) -> list[dict]:
    """The frozen bake-off lines in the canonical schema."""
    crops = {row["id"]: row for row in bakeoff.load_manifest()} if bakeoff.MANIFEST.is_file() else {}
    rows = []
    for row in frozen.rows:
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
                split=BAKEOFF_REGRESSION,
                source_type=REAL,
                verified="true",
                crop_sha256=row["crop_sha256"],
                image_width=crop.get("crop_width", ""),
                image_height=crop.get("crop_height", ""),
            )
        )
    return rows


# --- the training mix ----------------------------------------------------------


def load_mix(path: Path = MIX_CONFIG) -> dict:
    import yaml

    mix = yaml.safe_load(path.read_text(encoding="utf-8"))
    real, synthetic = mix["real_to_synthetic"]
    if mix["method"] not in MIX_METHODS or real <= 0 or synthetic < 0 or mix["max_real_repeats"] < 1:
        raise SystemExit(f"{path}: invalid mix {mix}.")
    return mix


def training_mix(real: list[dict], synthetic: list[dict], mix: dict) -> tuple[list[dict], dict]:
    """The rows of one training pass, and how real and synthetic lines balance in it.

    ``oversample_real`` repeats every real line until the pass holds the wanted
    share of real samples; ``subsample_synthetic`` keeps the real lines once
    and draws only as many synthetic lines as the ratio allows.
    """
    wanted_real, wanted_synthetic = mix["real_to_synthetic"]
    real = [row for row in real if row["subset"] != OUT_OF_VOCABULARY]
    repeats, kept = 1, list(synthetic)
    if real and mix["method"] == "oversample_real" and wanted_synthetic:
        target = len(synthetic) * wanted_real / wanted_synthetic
        repeats = min(mix["max_real_repeats"], max(1, round(target / len(real))))
    elif real and mix["method"] == "subsample_synthetic":
        keep = min(len(synthetic), round(len(real) * wanted_synthetic / wanted_real))
        kept = sorted(random.Random(mix["seed"]).sample(synthetic, keep), key=lambda row: row["id"])
    rows = real * repeats + kept
    report = {
        "method": mix["method"],
        "wanted_real_to_synthetic": f"{wanted_real}:{wanted_synthetic}",
        "real_lines": len(real),
        "real_repeats": repeats,
        "real_samples": len(real) * repeats,
        "synthetic_samples": len(kept),
        "samples_per_pass": len(rows),
        "real_share": round(len(real) * repeats / len(rows), 4) if rows else 0.0,
    }
    return rows, report


def mark_unencodable(rows: list[dict], vocabulary: str) -> int:
    """Flag the real lines VietOCR cannot encode; returns how many there are."""
    allowed = set(vocabulary)
    marked = [row for row in rows if set(row["text"]) - allowed]
    for row in marked:
        row["subset"] = OUT_OF_VOCABULARY
    return len(marked)


def write_vietocr_annotations(root: Path, name: str, rows: list[dict]) -> None:
    """One ``image path<TAB>label`` line per sample, the format VietOCR trains from.

    Lines VietOCR cannot encode are left out: its trainer stops on the first one.
    Written for the training and validation sets only. The bake-off regression
    and the blind test get no such file, so no config can be pointed at them.
    """
    rows = [row for row in rows if row["subset"] != OUT_OF_VOCABULARY]
    text = "".join(f"{row['image_path']}\t{row['text']}\n" for row in rows)
    dataset.write_text_atomic(root / "manifests" / "vietocr" / f"{name}_annotation.txt", text)


# --- rules ---------------------------------------------------------------------


def violations(splits: dict[str, list[dict]], regression: dataset.FrozenLines, banned_texts: frozenset[str]) -> list[str]:
    """Every reason the dataset about to be written must not exist."""
    problems = []
    others = [row for split, rows in splits.items() if split != BAKEOFF_REGRESSION for row in rows]
    problems += regression.leaks(others)
    problems += dataset.document_leaks(splits)

    owner_of_id: dict[str, str] = {}
    owner_of_image: dict[str, str] = {}
    for split, rows in splits.items():
        for row in rows:
            if row["id"] in owner_of_id:
                problems.append(f"{row['id']}: id used twice ({owner_of_id[row['id']]}, {split})")
            owner_of_id[row["id"]] = split
            first = owner_of_image.setdefault(row["crop_sha256"], split)
            if first != split:
                problems.append(f"{row['id']}: its image is also in {first}")

    training_texts = {row["text"] for row in splits[SYNTHETIC_TRAIN]}
    problems += [
        f"{row['id']}: text also in synthetic training"
        for row in splits[SYNTHETIC_VAL]
        if row["text"] in training_texts
    ]
    problems += [
        f"{row['id']}: text of a frozen bake-off line"
        for split in (SYNTHETIC_TRAIN, SYNTHETIC_VAL)
        for row in splits[split]
        if row["text"] in banned_texts
    ]
    return problems


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=dataset.DATASET_DIR, help="Where train/, val/ and manifests/ go.")
    parser.add_argument("--documents", type=Path, default=dataset.DOCUMENTS)
    parser.add_argument("--work-dir", type=Path, default=dataset.REAL_WORK_DIR)
    parser.add_argument("--hard-cases", type=Path, default=dataset.HARD_CASES)
    parser.add_argument("--mix", type=Path, default=MIX_CONFIG)
    parser.add_argument("--scale", type=float, default=1.0, help="Multiply every synthetic sample count.")
    parser.add_argument("--skip-synthetic", action="store_true", help="Keep the synthetic sets as they are.")
    parser.add_argument(
        "--allow-regression-texts",
        action="store_true",
        help="Let synthetic lines repeat the text of a frozen bake-off line (off by default).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    started = time.time()
    regression = dataset.FrozenLines.load(BAKEOFF_REGRESSION)
    banned = frozenset() if args.allow_regression_texts else frozenset(regression.texts)
    splits: dict[str, list[dict]] = {}
    report: dict = {"dataset": DATASET_NAME}
    report_path = args.root / "manifests" / "build_report.json"

    if args.skip_synthetic:
        for split in PILOT:
            path = dataset.manifest_path(split, args.root)
            if not path.is_file():
                raise SystemExit(f"{path} does not exist yet: build once without --skip-synthetic.")
            splits[split] = dataset.read_manifest(path)
        if report_path.is_file():
            # Keep what is known about how the synthetic sets were generated.
            previous = json.loads(report_path.read_text(encoding="utf-8"))
            report.update({key: previous[key] for key in GENERATION_KEYS if key in previous})
    else:
        import cv2
        import numpy

        from fonts import SERIF, discover
        from text_generator import Lexicon, TextGenerator, load_hard_cases

        fonts, rejected_fonts = discover(recognizer_vocabulary())
        if not any(font.category == SERIF for font in fonts):
            raise SystemExit("No Times-like font with full Vietnamese coverage was found on this system.")
        generator = TextGenerator(Lexicon(), recognizer_vocabulary(), banned)
        hard_cases = load_hard_cases(args.hard_cases)
        specs = {
            split: SplitSpec(
                spec.folder,
                spec.seed,
                max(1, round(spec.synthetic * args.scale)),
                max(1, round(spec.long_lines * args.scale)),
                max(1, round(spec.per_hard_case * args.scale)),
                max(1, round(spec.min_letter_occurrences * args.scale)),
            )
            for split, spec in PILOT.items()
        }
        seen: set[str] = set()
        for split, spec in specs.items():  # validation second, so it avoids every training text
            splits[split] = render_split(split_texts(generator, spec, hard_cases, seen), split, spec, fonts, args.root)
            print(f"{split}: rendered {len(splits[split])} lines")
        report.update(
            specification={split: asdict(spec) for split, spec in specs.items()},
            hard_cases=len(hard_cases),
            fonts_accepted=sorted(font.name for font in fonts),
            fonts_rejected=rejected_fonts,
            libraries={"pillow": version("pillow"), "opencv": cv2.__version__, "numpy": numpy.__version__},
        )

    documents = dataset.read_documents(args.documents)
    blind_file = dataset.frozen_path(BLIND_TEST, args.root)
    frozen_blind = dataset.load_frozen(BLIND_TEST, blind_file) if blind_file.is_file() else None
    splits.update(real_rows(documents, args.work_dir, args.root, frozen_blind))
    vocabulary = recognizer_vocabulary()
    unencodable = {split: mark_unencodable(splits[split], vocabulary) for split in (REAL_TRAIN, REAL_VAL)}
    splits[BAKEOFF_REGRESSION] = regression_rows(regression, args.root)
    splits = {split: splits[split] for split in dataset.SPLITS}

    problems = violations(splits, regression, banned)
    if problems:
        raise SystemExit("Build refused:\n  " + "\n  ".join(problems[:20]))

    mixed, mix_report = training_mix(splits[REAL_TRAIN], splits[SYNTHETIC_TRAIN], load_mix(args.mix))
    for split, rows in splits.items():
        dataset.write_manifest(dataset.manifest_path(split, args.root), rows)
        stale = args.root / "manifests" / "vietocr" / f"{split}_annotation.txt"
        if split in LEARNING_SPLITS:
            write_vietocr_annotations(args.root, split, rows)
        elif stale.is_file():
            stale.unlink()  # no trainer-readable file of an evaluation set
    write_vietocr_annotations(args.root, TRAIN_MIX, mixed)

    report.update(
        samples={
            split: dict(Counter(f"{row['source_type']}/{row['subset'] or 'general'}" for row in rows))
            for split, rows in splits.items()
        },
        fonts_used=dict(Counter(row["font"] for split in PILOT for row in splits[split] if row["font"])),
        synthetic_may_repeat_regression_texts=args.allow_regression_texts,
        blind_test_frozen=frozen_blind is not None,
        real_lines_outside_the_vocabulary=unencodable,
        training_mix=mix_report,
        seconds=round(time.time() - started, 1),
    )
    bakeoff.write_json(report_path, report)

    for split, rows in splits.items():
        print(f"{split}: {len(rows)} lines {dict(Counter(row['source_type'] for row in rows))}")
    print(
        f"training pass: {mix_report['real_samples']} real ({mix_report['real_lines']} lines x "
        f"{mix_report['real_repeats']}) + {mix_report['synthetic_samples']} synthetic = "
        f"{mix_report['samples_per_pass']} samples, real share {mix_report['real_share']:.1%}"
    )
    print(f"wrote manifests under {args.root / 'manifests'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Compare the OCR output of two benchmark profiles page by page.

Usage:
    python benchmarks/vietnamese/compare_profiles.py

Writes ``results/profile_comparison.csv``. This compares the two outputs with
each other, not with the truth: a higher confidence or a longer text does not
mean a profile is more accurate. Accuracy needs verified ground truth, see
``evaluate.py``.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from pathlib import Path

from common import (
    OUTPUT_ROOT,
    PROFILE_A,
    PROFILE_B,
    RESULTS_DIR,
    finished_documents,
    lines_to_text,
    load_page_lines,
    read_json,
)

COLUMNS = (
    "document",
    "page",
    "line_count_A",
    "line_count_B",
    "mean_confidence_A",
    "mean_confidence_B",
    "runtime_A",
    "runtime_B",
    "text_identical",
)
# The one setting the two profiles are allowed to differ in.
EXPECTED_DIFFERENCE = "use_doc_unwarping"


def flatten(value: object, prefix: str = "") -> dict[str, object]:
    """Nested dicts as ``{"a.b.c": leaf}``."""
    if not isinstance(value, dict):
        return {prefix: value}
    flat: dict[str, object] = {}
    for key, child in value.items():
        flat.update(flatten(child, f"{prefix}.{key}" if prefix else key))
    return flat


def configuration_differences(metadata_a: dict, metadata_b: dict) -> list[str]:
    flat_a = flatten(metadata_a["configuration"])
    flat_b = flatten(metadata_b["configuration"])
    return sorted(
        key for key in flat_a.keys() | flat_b.keys() if flat_a.get(key) != flat_b.get(key)
    )


def mean_confidence(lines: list[dict]) -> str:
    if not lines:
        return ""
    return f"{statistics.fmean(line['confidence'] for line in lines):.6f}"


def compare(output_root: Path, profile_a: str, profile_b: str) -> list[dict]:
    dir_a, dir_b = output_root / profile_a, output_root / profile_b
    documents = finished_documents(dir_a)
    if not documents:
        raise SystemExit(f"No finished documents in {dir_a}. Run run_benchmark.py first.")
    if documents != finished_documents(dir_b):
        raise SystemExit(f"{dir_a} and {dir_b} do not hold the same documents.")

    rows = []
    for document in documents:
        metadata_a = read_json(dir_a / document / "metadata.json")
        metadata_b = read_json(dir_b / document / "metadata.json")
        if metadata_a["input"]["sha256"] != metadata_b["input"]["sha256"]:
            raise SystemExit(f"{document}: the two profiles ran on different input files.")
        unexpected = [
            key
            for key in configuration_differences(metadata_a, metadata_b)
            if not key.endswith(EXPECTED_DIFFERENCE)
        ]
        if unexpected:
            raise SystemExit(
                f"{document}: profiles differ in more than {EXPECTED_DIFFERENCE}: "
                + ", ".join(unexpected)
            )

        lines_a = load_page_lines(dir_a / document)
        lines_b = load_page_lines(dir_b / document)
        runtime_a = {p["page"]: p["elapsed_seconds"] for p in metadata_a["pages"]}
        runtime_b = {p["page"]: p["elapsed_seconds"] for p in metadata_b["pages"]}
        for page in sorted(lines_a.keys() | lines_b.keys()):
            page_a, page_b = lines_a.get(page, []), lines_b.get(page, [])
            rows.append(
                {
                    "document": document,
                    "page": page,
                    "line_count_A": len(page_a),
                    "line_count_B": len(page_b),
                    "mean_confidence_A": mean_confidence(page_a),
                    "mean_confidence_B": mean_confidence(page_b),
                    "runtime_A": runtime_a.get(page, ""),
                    "runtime_B": runtime_b.get(page, ""),
                    "text_identical": lines_to_text(page_a) == lines_to_text(page_b),
                }
            )
    return rows


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile-a", default=PROFILE_A.name)
    parser.add_argument("--profile-b", default=PROFILE_B.name)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = compare(args.output_root, args.profile_a, args.profile_b)

    args.results_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.results_dir / "profile_comparison.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    identical = sum(row["text_identical"] for row in rows)
    print(f"A = {args.profile_a}")
    print(f"B = {args.profile_b}")
    print(f"pages compared:            {len(rows)}")
    print(f"pages with identical text: {identical}")
    print(f"pages with different text: {len(rows) - identical}")
    print(f"total lines A / B:         "
          f"{sum(r['line_count_A'] for r in rows)} / {sum(r['line_count_B'] for r in rows)}")
    print(f"total runtime A / B (s):   "
          f"{sum(r['runtime_A'] or 0 for r in rows):.1f} / "
          f"{sum(r['runtime_B'] or 0 for r in rows):.1f}")
    print(f"wrote {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

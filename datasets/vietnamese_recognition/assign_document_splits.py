#!/usr/bin/env python3
"""Assign every registered real document, as a whole, to train, validation or blind test.

Usage:
    python datasets/vietnamese_recognition/assign_document_splits.py
    python datasets/vietnamese_recognition/assign_document_splits.py --set doc_0123456789ab=val

The split is by document, never by page or line: one document belongs to
exactly one set, so no two sets ever share a scan, a layout or a sentence
continued over a line break.

Unassigned documents are taken in an order derived from their content hash,
which has nothing to do with their names, their dates or what they say. Each
set has a planned number of documents:

    blind   a fifth of the documents, at least 2
    val     a fifth of the documents, at least 2
    train   all the others

so ten to twelve documents give two for the blind test, two for validation
and six to eight for training. A new document goes to the blind test while
that set is below its number, then to validation, then to training. Nobody
looks at a document to decide where it goes, which is what keeps the blind
test blind.

Two documents may not hold the 100 verified lines the blind test and the
validation set each need. The script says so when a set has fewer than 130
detected lines; the answer is to bring more documents, not to move lines.

An assignment is never changed by a later run. ``--set`` moves a document by
hand, and only while none of its lines has been annotated.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections import Counter
from pathlib import Path

import dataset_common as dataset

import bakeoff_common as bakeoff  # noqa: E402  (path set up by dataset_common)

ORDER_SALT = "vietnamese-recognition-document-split-v1"
# Filled in this order; the last one takes whatever is left.
FILL_ORDER = ("blind", "val", "train")
EVALUATION_SHARE = 0.2  # of the documents, for the blind test and for validation each
MIN_EVALUATION_DOCUMENTS = 2
# Detected lines a set should have to yield about 100 verified readable ones.
ENOUGH_DETECTED_LINES = 130


def order_key(sha256: str) -> str:
    return hashlib.sha256(f"{ORDER_SALT}:{sha256}".encode("utf-8")).hexdigest()


def line_counts(lines: Path) -> Counter:
    if not lines.is_file():
        return Counter()
    return Counter(row["document_id"] for row in bakeoff.load_manifest(lines))


def annotated_documents(annotation_dir: Path) -> set[str]:
    """Documents with at least one line a person has verified or set aside."""
    touched = set()
    for table in sorted(annotation_dir.glob(f"*/{bakeoff.ANNOTATION_MANIFEST.name}")):
        for row in bakeoff.read_annotation(table):
            if bakeoff.is_verified(row) or bakeoff.is_excluded(row):
                touched.add(row["document"])
    return touched


def planned_documents(total: int) -> dict[str, int]:
    """How many documents the blind test and validation are meant to hold."""
    share = max(MIN_EVALUATION_DOCUMENTS, round(EVALUATION_SHARE * total))
    return {"blind": share, "val": share}


def assign(documents: list[dict]) -> list[str]:
    """Give every unassigned document a split, in hash order. Returns the ids assigned."""
    planned = planned_documents(len(documents))
    assigned = []
    for document in sorted((d for d in documents if not d["split"]), key=lambda d: order_key(d["sha256"])):
        members = Counter(d["split"] for d in documents)
        document["split"] = next(
            (split for split in FILL_ORDER[:-1] if members[split] < planned[split]), FILL_ORDER[-1]
        )
        document["blind"] = "true" if document["split"] == "blind" else "false"
        assigned.append(document["document_id"])
    return assigned


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--documents", type=Path, default=dataset.DOCUMENTS)
    parser.add_argument("--lines", type=Path, default=dataset.REAL_LINES)
    parser.add_argument("--annotation-dir", type=Path, default=dataset.REAL_ANNOTATION_DIR)
    parser.add_argument("--set", action="append", default=[], metavar="DOCUMENT_ID=SPLIT",
                        help="Move one document by hand (train, val or blind); only before it is annotated.")  # fmt: skip
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    documents = dataset.read_documents(args.documents)
    if not documents:
        print("No registered document yet.")
        return 0
    by_id = {document["document_id"]: document for document in documents}
    lines = line_counts(args.lines)

    locked = annotated_documents(args.annotation_dir)
    for request in args.set:
        identifier, _, split = request.partition("=")
        if identifier not in by_id or split not in dataset.DOCUMENT_SPLITS:
            raise SystemExit(f"--set {request}: expected <document_id>=<train|val|blind>.")
        if identifier in locked and by_id[identifier]["split"] != split:
            raise SystemExit(f"{identifier} already has annotated lines; its split can no longer change.")
        by_id[identifier]["split"] = split
        by_id[identifier]["blind"] = "true" if split == "blind" else "false"

    assigned = assign(documents)
    dataset.write_documents(documents, args.documents)

    print(f"documents: {len(documents)} ({len(assigned)} assigned now)")
    for split in FILL_ORDER:
        members = [d for d in documents if d["split"] == split]
        print(f"  {split:5s}: {len(members)} document(s), {sum(lines[d['document_id']] for d in members)} detected line(s)")
        for document in members:
            mark = " (annotation started)" if document["document_id"] in locked else ""
            print(f"         {document['document_id']}  {lines[document['document_id']]:4d} lines{mark}")
        detected = sum(lines[d["document_id"]] for d in members)
        if split != "train" and lines and detected < ENOUGH_DETECTED_LINES:
            print(f"         note: {detected} detected lines may not yield 100 verified ones; more documents are needed")
    if not documents or Counter(d["split"] for d in documents)["train"] == 0:
        print("  note: no training document yet")
    return 0


if __name__ == "__main__":
    sys.exit(main())

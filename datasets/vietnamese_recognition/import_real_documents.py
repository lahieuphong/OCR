#!/usr/bin/env python3
"""Register the new real documents dropped into ``real_source/``.

Usage:
    python datasets/vietnamese_recognition/import_real_documents.py --note "<where they come from>"

Accepts PDF, PNG, JPEG and TIFF files, recognised by their content and not by
their extension. For every document it records, in ``real_documents.tsv``:

    document_id   ``doc_`` plus the first 12 hex digits of the SHA-256
    filename      the name it had when imported (informational only)
    sha256        of the file: this, not the name, is the document's identity
    page_count
    file_type
    source_note   free text; edit the column by hand, it is kept on re-import
    split, blind  filled in later by assign_document_splits.py

A file is refused when it is one of the three bake-off documents: the new
dataset must come from other documents. The same content under two names is
one document.

The source files themselves stay in ``real_source/``, which git ignores. This
script only reads them and links them, under their document id, into
``real_work/staged/`` for the detection step.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import dataset_common as dataset

FILE_TYPES = {
    b"%PDF": "pdf",
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpeg",
    b"II*\x00": "tiff",
    b"MM\x00*": "tiff",
}
STAGED_SUFFIX = {"pdf": ".pdf", "png": ".png", "jpeg": ".jpg", "tiff": ".tif"}
ID_DIGITS = 12


def file_type(path: Path) -> str | None:
    """The kind of document, read from the first bytes of the file."""
    with path.open("rb") as stream:
        head = stream.read(16)
    return next((name for magic, name in FILE_TYPES.items() if head.startswith(magic)), None)


def page_count(path: Path, kind: str) -> int:
    if kind == "pdf":
        import pypdfium2

        document = pypdfium2.PdfDocument(str(path))
        try:
            return len(document)
        finally:
            document.close()
    if kind == "tiff":
        from PIL import Image

        with Image.open(path) as image:
            return getattr(image, "n_frames", 1)
    return 1


def document_id(sha256: str) -> str:
    return f"doc_{sha256[:ID_DIGITS]}"


def stage(source: Path, kind: str, pages: int, target_dir: Path, identifier: str) -> Path:
    """Make the document available under its id for the detection step.

    A multi-page TIFF is rewritten as a PDF, because the OCR pipeline reads
    only the first page of a TIFF. Everything else is linked unchanged.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    for stale in target_dir.glob(f"{identifier}.*"):
        stale.unlink()
    if kind == "tiff" and pages > 1:
        from PIL import Image, ImageSequence

        target = target_dir / f"{identifier}.pdf"
        with Image.open(source) as image:
            frames = [frame.convert("RGB") for frame in ImageSequence.Iterator(image)]
        frames[0].save(target, "PDF", save_all=True, append_images=frames[1:], resolution=150.0)
        return target
    target = target_dir / f"{identifier}{STAGED_SUFFIX[kind]}"
    target.symlink_to(source.resolve())
    return target


def scan(source_dir: Path, excluded: dict[str, str]) -> tuple[dict[str, dict], list[str]]:
    """Documents found in ``source_dir`` by SHA-256, and what was passed over and why."""
    found: dict[str, dict] = {}
    notes = []
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        kind = file_type(path)
        if kind is None:
            notes.append(f"skipped {path.name}: not a PDF, PNG, JPEG or TIFF file")
            continue
        digest = dataset.sha256_file(path)
        if digest in excluded:
            notes.append(f"REFUSED {path.name}: it is the bake-off document {excluded[digest]}")
        elif digest in found:
            notes.append(f"skipped {path.name}: same content as {found[digest]['path'].name}")
        else:
            found[digest] = {"path": path, "file_type": kind, "page_count": page_count(path, kind)}
    return found, notes


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source-dir", type=Path, default=dataset.REAL_SOURCE_DIR)
    parser.add_argument("--documents", type=Path, default=dataset.DOCUMENTS)
    parser.add_argument("--staged-dir", type=Path, default=dataset.REAL_WORK_DIR / "staged")
    parser.add_argument("--benchmark-documents", type=Path, default=dataset.BENCHMARK_DOCUMENTS)
    parser.add_argument("--note", default="", help="Source note for the documents registered by this run.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.source_dir.is_dir():
        raise SystemExit(f"No source directory: {args.source_dir}")
    registry = {row["sha256"]: row for row in dataset.read_documents(args.documents)}
    found, notes = scan(args.source_dir, dataset.benchmark_documents(args.benchmark_documents))

    added = []
    for digest, info in found.items():
        identifier = document_id(digest)
        clash = next((row for row in registry.values() if row["document_id"] == identifier and row["sha256"] != digest), None)
        if clash:
            raise SystemExit(f"{info['path'].name} and {clash['filename']} share the id {identifier}; widen ID_DIGITS.")
        if digest not in registry:
            registry[digest] = {
                "document_id": identifier,
                "filename": info["path"].name,
                "sha256": digest,
                "page_count": info["page_count"],
                "file_type": info["file_type"],
                "source_note": args.note,
                "split": "",
                "blind": "false",
            }
            added.append(identifier)
        stage(info["path"], info["file_type"], info["page_count"], args.staged_dir, identifier)
    dataset.write_documents(list(registry.values()), args.documents)

    absent = [row["document_id"] for digest, row in registry.items() if digest not in found]
    for note in notes:
        print(note)
    print(f"documents registered: {len(registry)} ({len(added)} new)")
    for row in sorted(registry.values(), key=lambda row: row["document_id"]):
        print(f"  {row['document_id']}  {row['file_type']:4s} {int(row['page_count']):3d} page(s)  "
              f"split={row['split'] or '-':5s} {row['filename']}")
    if absent:
        print(f"registered earlier but no longer in {args.source_dir.name}/: {', '.join(absent)}")
    refused = sum(note.startswith("REFUSED") for note in notes)
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())

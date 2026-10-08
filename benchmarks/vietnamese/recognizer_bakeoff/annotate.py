#!/usr/bin/env python3
"""Verify the ground truth of the selected line crops, one crop at a time.

Usage:
    python benchmarks/vietnamese/recognizer_bakeoff/annotate.py          # browser page
    python benchmarks/vietnamese/recognizer_bakeoff/annotate.py --cli    # terminal

Each crop is shown with what the two recognizers predicted. The annotator then
takes one of these actions:

    p   the PP-OCRv6 text matches the crop exactly
    v   the VietOCR text matches the crop exactly
    e   type, or edit, the exact text of the crop
    s   set the line aside (handwriting, stamp over the text, unreadable ...)
    q   save and quit

``p`` and ``v`` are statements by the person looking at the crop, not shortcuts
that trust a model: neither prediction is ever accepted by default, and
pressing Enter alone does nothing. The ground truth is stored in Unicode NFC.

The table is saved after every action, so a session can stop at any point and
the next run resumes where it left off. Lines are shown in an order that
alternates between documents, pages and kinds of line, and the session ends by
itself once the target number of verified lines is reached. A verified line is
only ever changed by asking for it: ``--id`` names rows, and ``--recheck``
goes again through every line verified in a given way, for instance all lines
where a prediction was accepted as it stood.
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

import bakeoff_common as bakeoff
from annotation_store import (
    ACCEPTED_SOURCE,
    SKIP_REASONS,
    TARGET_VERIFIED,
    TYPED_SOURCE,
    ActionError,
    AnnotationStore,
    load_selection,
    normalise,
)

CURRENT_CROP = "_current.png"
MENU = """\
[p] accept PP-OCRv6 text
[v] accept VietOCR text
[e] enter/edit exact ground truth
[s] skip this line
[q] save and quit        ([o] open the image, [u] undo the last action)"""


def git_user_name() -> str:
    try:
        completed = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True,
            text=True,
            check=False,
            cwd=bakeoff.REPO_ROOT,
        )
    except OSError:
        return ""
    return completed.stdout.strip()


def open_in_viewer(path: Path) -> None:
    system = platform.system()
    if system == "Darwin":
        command = ["open", "-g", str(path)]  # -g: do not take focus from the terminal
    elif system == "Linux" and shutil.which("xdg-open"):
        command = ["xdg-open", str(path)]
    else:
        return
    subprocess.run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ask_typed_text(ask: Callable[[str], str], say: Callable[[str], None]) -> str | None:
    """Text typed by the annotator and confirmed, or None when cancelled."""
    while True:
        raw = ask("exact ground truth> ")
        if not normalise(raw):
            say("Nothing typed; back to the menu.")
            return None
        say(f"you typed: {normalise(raw)!r} ({len(normalise(raw))} characters)")
        answer = ask("[y] save as verified   [r] retype   [c] cancel: ").strip().lower()
        if answer == "y":
            return raw
        if answer != "r":
            return None


def ask_skip_reason(ask: Callable[[str], str], say: Callable[[str], None]) -> str | None:
    reasons = list(SKIP_REASONS)
    for number, reason in enumerate(reasons, start=1):
        say(f"  [{number}] {SKIP_REASONS[reason]}")
    answer = ask("reason (number, anything else cancels): ").strip()
    if answer.isdigit() and 1 <= int(answer) <= len(reasons):
        return reasons[int(answer) - 1]
    return None


def run_cli(
    store: AnnotationStore,
    crop_file: Callable[[dict], Path],
    mirror: Callable[[Path], Path] = lambda crop: crop,
    ask: Callable[[str], str] = input,
    say: Callable[[str], None] = print,
    opener: Callable[[Path], None] = open_in_viewer,
) -> None:
    """The terminal front end: one menu per crop.

    ``mirror`` copies the current crop to one fixed file and returns it. An
    image viewer left open on that file follows the session, and ``o`` opens
    that same file, so no window piles up per line.
    """
    try:
        while (row := store.current()) is not None:
            progress = store.progress()
            image = crop_file(row)
            viewed = mirror(image)
            say("")
            say(
                f"--- verified {progress['verified']}/{progress['target']}, "
                f"skipped {progress['skipped']}, not yet seen {progress['pending']} ---"
            )
            say(f"ID:\n{row['id']}")
            say(f"Document:\n{row['document']}")
            say(f"Page:\n{row['page']}")
            say(f"\nPP-OCRv6:\n{row['ppocr_prediction']}")
            say(f"\nVietOCR:\n{row['vietocr_prediction']}")
            say(f"\nImage:\n{image}\n")
            say(MENU)
            choice = ask("> ").strip().lower()
            try:
                if choice == "p":
                    store.accept(row["id"], bakeoff.PPOCR)
                elif choice == "v":
                    store.accept(row["id"], bakeoff.VIETOCR)
                elif choice == "e":
                    raw = ask_typed_text(ask, say)
                    if raw is not None:
                        store.enter(row["id"], raw)
                elif choice == "s":
                    reason = ask_skip_reason(ask, say)
                    if reason is not None:
                        store.skip(row["id"], reason)
                elif choice == "u":
                    say(f"undone: {store.undo()['id']}")
                elif choice == "o":
                    opener(viewed)
                elif choice == "q":
                    store.stop()
                else:
                    # Includes a bare Enter: no prediction is ever accepted by default.
                    say("Nothing was saved. Choose p, v, e, s or q.")
            except ActionError as error:
                say(str(error))
    except (EOFError, KeyboardInterrupt):
        say("")
        store.stop()


def rows_to_reopen(table_path: Path, ids: list[str] | None, source: str | None) -> list[str] | None:
    """Ids the annotator asked to see again, or None for an ordinary session."""
    reopened = list(ids or [])
    if source:
        reopened += [
            row["id"]
            for row in bakeoff.read_annotation(table_path)
            if bakeoff.is_verified(row) and row["ground_truth_source"] == source and row["id"] not in reopened
        ]
        if not reopened:
            raise SystemExit(f"No verified line has ground_truth_source={source}.")
    return reopened or None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--annotator", default=None, help="Name of the person annotating (default: git user.name)."
    )
    parser.add_argument(
        "--target", type=int, default=TARGET_VERIFIED, help="Stop at this many verified lines."
    )
    parser.add_argument("--cli", action="store_true", help="Annotate in the terminal, not the browser.")
    parser.add_argument("--port", type=int, default=8765, help="Port of the browser page (0: any free).")
    parser.add_argument("--no-open", action="store_true", help="Do not open the browser page.")
    parser.add_argument("--id", action="append", help="Redo this row (repeatable), even if verified.")
    parser.add_argument(
        "--recheck",
        choices=sorted([*ACCEPTED_SOURCE.values(), TYPED_SOURCE]),
        help="Go again through every line that was verified this way.",
    )
    parser.add_argument("--annotation-dir", type=Path, default=bakeoff.ANNOTATION_DIR)
    parser.add_argument("--manifest", type=Path, default=bakeoff.MANIFEST)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    annotator = args.annotator or git_user_name()
    if not annotator:
        raise SystemExit("Pass --annotator: no git user.name is configured.")
    base_dir = args.manifest.parent
    exported = {row["id"]: row["crop_sha256"] for row in bakeoff.load_manifest(args.manifest)}
    table_path = args.annotation_dir / bakeoff.ANNOTATION_MANIFEST.name
    reopened = rows_to_reopen(table_path, args.id, args.recheck)
    store = AnnotationStore(
        table_path,
        args.annotation_dir / bakeoff.ANNOTATION_LOG.name,
        annotator,
        target=args.target,
        selection=load_selection(args.annotation_dir / bakeoff.SELECTION_REPORT.name),
        only_ids=reopened,
    )
    mirror = args.annotation_dir / bakeoff.CANDIDATES_DIR.name / CURRENT_CROP

    def crop_file(row: dict) -> Path:
        crop = base_dir / row["crop_path"]
        # The annotator must look at the very file the recognizers read.
        if not crop.is_file() or bakeoff.sha256_file(crop) != exported.get(row["id"]):
            raise SystemExit(f"{crop} is missing or is not the exported crop of {row['id']}.")
        return crop

    def mirror_crop(crop: Path) -> Path:
        mirror.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(crop, mirror)
        return mirror

    if store.current() is None:
        print(f"Nothing to annotate: {store.stop_reason()}.")
    elif args.cli:
        run_cli(store, crop_file, mirror_crop)
    else:
        from annotation_server import AnnotationApp, serve

        serve(AnnotationApp(store, crop_file), args.port, open_browser=not args.no_open)

    progress = store.progress()
    print(
        f"{store.stop_reason()}: verified {progress['verified']}/{progress['target']}, "
        f"skipped {progress['skipped']}, not yet seen {progress['pending']}; "
        f"{progress['documents']} document(s), {progress['pages']} page(s)."
    )
    if progress["verified"] >= args.target and not reopened:
        if progress["missing_coverage"]:
            print("Not covered by the verified lines: " + ", ".join(progress["missing_coverage"]))
        print("Next: python benchmarks/vietnamese/recognizer_bakeoff/evaluate_recognizers.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Type the ground truth of the selected line crops, one crop at a time.

Usage:
    python benchmarks/vietnamese/recognizer_bakeoff/annotate.py --annotator "<name>"

For each unverified row of ``annotation/manifest.tsv`` this shows the crop
path and what the two recognizers predicted, then asks for the text that is
really in the image. The current crop is also copied to
``annotation/candidates/_current.png``: keep that file open in an image viewer
that reloads on change (VS Code does) and it follows along.

The tool never fills in the answer. It does not pick one of the predictions,
does not correct spelling and does not complete anything: the ground truth is
what the annotator types, with leading and trailing spaces removed and the
text stored in Unicode NFC. The exact keystrokes are kept in
``annotation/annotation_log.jsonl``.

A row becomes ``verified=true`` only when the annotator confirms it, and the
table is saved after every confirmation, so quitting loses nothing.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import bakeoff_common as bakeoff

try:  # line editing (arrow keys, history) inside input(), where available
    import readline  # noqa: F401
except ImportError:
    pass

CURRENT_CROP = "_current.png"
SKIP, EMPTY, QUIT = ":s", ":e", ":q"
HELP = f"commands: {SKIP} skip this crop   {EMPTY} the crop contains no text   {QUIT} save and quit"


class Quit(Exception):
    """The annotator asked to stop."""


def normalise(raw: str) -> str:
    """Ground truth as stored: NFC, without leading or trailing whitespace."""
    return unicodedata.normalize("NFC", raw.strip())


def open_in_viewer(path: Path) -> None:
    system = platform.system()
    if system == "Darwin":
        command = ["open", "-g", str(path)]  # -g: do not take focus from the terminal
    elif system == "Linux" and shutil.which("xdg-open"):
        command = ["xdg-open", str(path)]
    else:
        return
    subprocess.run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ask_ground_truth(
    row: dict, ask: Callable[[str], str], say: Callable[[str], None]
) -> tuple[str, str] | None:
    """``(keystrokes, ground truth)`` once confirmed, or None when the row is skipped."""
    draft = row["ground_truth"]
    while True:
        if draft:
            say(f"draft:    {draft}   (press Enter to keep it)")
        raw = ask("ground truth> ")
        command = raw.strip()
        if command == QUIT:
            raise Quit
        if command == SKIP:
            return None
        if command == EMPTY:
            raw = ""
        elif not command:
            if not draft:
                say(f"nothing typed. {HELP}")
                continue
            raw = draft
        if "\t" in raw:
            say("the text contains a tab character; type it again without one")
            continue

        text = normalise(raw)
        say(f"you typed: {text!r} ({len(text)} characters)" if text else "you marked: no text in this crop")
        answer = ask("[y] save as verified   [r] retype   [s] skip: ").strip().lower()
        if answer == "y":
            return raw, text
        if answer == "s":
            return None
        if answer == QUIT:
            raise Quit


def run_session(
    rows: list[dict],
    todo: list[dict],
    save: Callable[[dict, str, str], None],
    show_crop: Callable[[dict], Path],
    ask: Callable[[str], str] = input,
    say: Callable[[str], None] = print,
) -> int:
    """Walk through ``todo``; returns how many rows were verified."""
    done = 0
    try:
        for position, row in enumerate(todo, start=1):
            verified = sum(bakeoff.is_verified(r) for r in rows)
            say("")
            say(f"[{position}/{len(todo)}] {row['id']}   ({row['document']}, page {row['page']})"
                f"   verified so far: {verified}/{len(rows)}")
            say(f"crop:     {show_crop(row)}")
            say(f"PP-OCRv6: {row['ppocr_prediction']}")
            say(f"VietOCR:  {row['vietocr_prediction']}")
            say(HELP)
            answer = ask_ground_truth(row, ask, say)
            if answer is None:
                say("skipped")
                continue
            raw, text = answer
            row["ground_truth"], row["verified"] = text, "true"
            save(row, raw, text)
            done += 1
    except (Quit, EOFError, KeyboardInterrupt):
        say("\nstopped")
    return done


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--annotator", required=True, help="Name of the person typing.")
    parser.add_argument("--annotation-dir", type=Path, default=bakeoff.ANNOTATION_DIR)
    parser.add_argument("--manifest", type=Path, default=bakeoff.MANIFEST)
    parser.add_argument("--id", action="append", help="Only this row (repeatable), verified or not.")
    parser.add_argument("--redo", action="store_true", help="Go through verified rows again too.")
    parser.add_argument("--no-open", action="store_true", help="Do not launch an image viewer.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    table_path = args.annotation_dir / bakeoff.ANNOTATION_MANIFEST.name
    log_path = args.annotation_dir / bakeoff.ANNOTATION_LOG.name
    base_dir = args.manifest.parent
    rows = bakeoff.read_annotation(table_path)
    exported = {row["id"]: row for row in bakeoff.load_manifest(args.manifest)}

    if args.id:
        unknown = sorted(set(args.id) - {row["id"] for row in rows})
        if unknown:
            raise SystemExit(f"Not in {table_path}: {', '.join(unknown)}")
        todo = [row for row in rows if row["id"] in args.id]
    else:
        todo = [row for row in rows if args.redo or not bakeoff.is_verified(row)]
    if not todo:
        print("Nothing to annotate: every row is verified.")
        return 0

    current = args.annotation_dir / bakeoff.CANDIDATES_DIR.name / CURRENT_CROP
    viewer_started = args.no_open

    def show_crop(row: dict) -> Path:
        nonlocal viewer_started
        crop = base_dir / row["crop_path"]
        # The annotator must look at the very file the recognizers read.
        if not crop.is_file() or bakeoff.sha256_file(crop) != exported[row["id"]]["crop_sha256"]:
            raise SystemExit(f"{crop} is missing or is not the exported crop of {row['id']}.")
        current.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(crop, current)
        if not viewer_started:
            open_in_viewer(current)
            viewer_started = True
        return crop

    def save(row: dict, raw: str, text: str) -> None:
        bakeoff.write_annotation(table_path, rows)
        entry = {
            "id": row["id"],
            "raw_input": raw,
            "ground_truth": text,
            "annotator": args.annotator,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        with log_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"{len(todo)} crop(s) to annotate. The current crop is mirrored to {current}")
    done = run_session(rows, todo, save, show_crop)
    verified = sum(bakeoff.is_verified(row) for row in rows)
    print(f"verified in this session: {done}; verified in total: {verified}/{len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

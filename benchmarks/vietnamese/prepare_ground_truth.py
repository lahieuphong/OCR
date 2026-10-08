#!/usr/bin/env python3
"""Annotation helper: OCR candidates in, human-verified ground truth out.

Step 1 - create candidates from the OCR output of one profile:

    python benchmarks/vietnamese/prepare_ground_truth.py candidates \
        --profile ppocrv6_vi_unwarp_off

  Writes ``annotation_candidates/<document>/page_XXXX.txt`` (the OCR text,
  unchanged) next to ``page_XXXX.png`` (the page image). Candidates are marked
  ``verified: false`` and are never used as ground truth.

Step 2 - a person corrects each ``page_XXXX.txt`` against its image.

Step 3 - that person records the page as verified:

    python benchmarks/vietnamese/prepare_ground_truth.py verify \
        --document <document> --page 1 --verified-by "<name>"

  Copies the corrected text to ``ground_truth/pages/<document>/`` and marks it
  ``verified: true``. Only run this for a page you have read line by line
  against the image: the evaluation trusts this flag.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from common import (
    CANDIDATES_DIR,
    GROUND_TRUTH_DIR,
    OUTPUT_ROOT,
    PROFILES,
    finished_documents,
    ground_truth_metadata_path,
    lines_to_text,
    load_page_lines,
    load_verified_ground_truth,
    page_tag,
    read_json,
    sha256_file,
    write_json,
    write_text,
)


def load_or_new_metadata(path: Path, document: str) -> dict:
    return read_json(path) if path.is_file() else {"document": document, "pages": {}}


def create_candidates(args: argparse.Namespace) -> int:
    profile_dir = args.output_root / args.profile
    documents = finished_documents(profile_dir)
    if not documents:
        raise SystemExit(f"No finished documents in {profile_dir}. Run run_benchmark.py first.")
    verified, _ = load_verified_ground_truth(args.ground_truth_dir)

    created = kept = already_verified = 0
    for document in documents:
        output_dir = profile_dir / document
        run_metadata = read_json(output_dir / "metadata.json")
        candidate_dir = args.candidates_dir / document
        metadata_path = candidate_dir / "metadata.json"
        metadata = load_or_new_metadata(metadata_path, document)
        # The source file is not in git: its hash ties the text to one exact file.
        metadata["input"] = {
            "name": Path(run_metadata["input"]["path"]).name,
            "sha256": run_metadata["input"]["sha256"],
        }

        for page, lines in sorted(load_page_lines(output_dir).items()):
            tag = page_tag(page)
            if (document, page) in verified:
                already_verified += 1
                continue

            text_path = candidate_dir / f"{tag}.txt"
            entry = metadata["pages"].get(tag)
            # A candidate that no longer matches its recorded hash has been
            # edited by an annotator: never replace that work silently.
            edited = text_path.exists() and (
                entry is None or sha256_file(text_path) != entry["candidate_sha256"]
            )
            if edited and not args.force:
                print(f"kept    {document}/{tag}.txt (edited by hand; --force to replace)")
                kept += 1
                continue

            text = lines_to_text(lines) + "\n"
            write_text(text_path, text)
            shutil.copyfile(output_dir / "raw" / f"{tag}.png", candidate_dir / f"{tag}.png")
            metadata["pages"][tag] = {
                "verified": False,
                "source_profile": args.profile,
                "source_repo_commit": run_metadata["repo_commit"],
                "candidate_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "image": f"{tag}.png",
            }
            created += 1
        if metadata["pages"]:
            write_json(metadata_path, metadata)

    print(
        f"candidates written: {created}, kept (edited by hand): {kept}, "
        f"skipped (already verified): {already_verified}"
    )
    print(f"location: {args.candidates_dir}")
    print("These are OCR output, not ground truth (verified: false).")
    return 0


def verify_pages(args: argparse.Namespace) -> int:
    candidate_dir = args.candidates_dir / args.document
    candidate_metadata = load_or_new_metadata(candidate_dir / "metadata.json", args.document)
    metadata_path = ground_truth_metadata_path(args.ground_truth_dir, args.document)
    metadata = load_or_new_metadata(metadata_path, args.document)
    if "input" in candidate_metadata:
        metadata["input"] = candidate_metadata["input"]

    for page in args.page:
        tag = page_tag(page)
        target = args.ground_truth_dir / args.document / f"{tag}.txt"
        entry = metadata["pages"].get(tag, {})

        if target.exists():
            if entry.get("verified") is True and entry.get("sha256") == sha256_file(target):
                raise SystemExit(
                    f"{args.document}/{tag}.txt is already verified and is never "
                    "overwritten. To redo it, edit that file and run verify again."
                )
            # The ground-truth file was edited in place: attest it as it is now.
            print(f"re-verifying {target} as it is now (candidate not copied)")
        else:
            candidate = candidate_dir / f"{tag}.txt"
            if not candidate.is_file():
                raise SystemExit(f"No candidate to verify: {candidate}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(candidate, target)

        candidate_entry = candidate_metadata["pages"].get(tag, {})
        digest = sha256_file(target)
        identical = digest == candidate_entry.get("candidate_sha256")
        metadata["pages"][tag] = {
            "verified": True,
            "verified_by": args.verified_by,
            "verified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sha256": digest,
            "source_profile": candidate_entry.get("source_profile"),
            "candidate_sha256": candidate_entry.get("candidate_sha256"),
            "identical_to_candidate": identical,
        }
        print(f"verified {args.document}/{tag}.txt by {args.verified_by}")
        if identical:
            print(
                "  note: this text is byte-identical to the unedited OCR candidate. "
                "That is only right if the OCR made no mistake on this page."
            )
    write_json(metadata_path, metadata)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)

    candidates = commands.add_parser("candidates", help="Create OCR candidates to correct.")
    candidates.add_argument("--profile", required=True, choices=sorted(PROFILES))
    candidates.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    candidates.add_argument(
        "--force", action="store_true", help="Replace candidates that were edited by hand."
    )
    candidates.set_defaults(handler=create_candidates)

    verify = commands.add_parser("verify", help="Record pages a person has checked.")
    verify.add_argument("--document", required=True)
    verify.add_argument("--page", required=True, type=int, nargs="+")
    verify.add_argument("--verified-by", required=True, help="Name of the person who checked.")
    verify.set_defaults(handler=verify_pages)

    for command in (candidates, verify):
        command.add_argument("--candidates-dir", type=Path, default=CANDIDATES_DIR)
        command.add_argument("--ground-truth-dir", type=Path, default=GROUND_TRUTH_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())

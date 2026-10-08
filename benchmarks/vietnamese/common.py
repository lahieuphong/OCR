"""Shared definitions for the Vietnamese benchmark scripts.

Paths, the benchmark profiles, and readers for OCR output and ground truth.
Nothing here changes recognised text: predictions are read back exactly as
``run_ocr.py`` wrote them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

BENCHMARK_DIR = Path(__file__).resolve().parent
REPO_ROOT = BENCHMARK_DIR.parents[1]
BASELINE_DIR = REPO_ROOT / "experiments" / "vietnamese_baseline"
OUTPUT_ROOT = BASELINE_DIR / "output"
GROUND_TRUTH_DIR = BENCHMARK_DIR / "ground_truth" / "pages"
CANDIDATES_DIR = BENCHMARK_DIR / "annotation_candidates"
RESULTS_DIR = BENCHMARK_DIR / "results"
HARD_CASES_FILE = BENCHMARK_DIR / "hard_cases.txt"


@dataclass(frozen=True)
class Profile:
    name: str
    lang: str
    ocr_version: str
    detection_model: str
    recognition_model: str
    use_doc_orientation_classify: bool
    use_doc_unwarping: bool
    use_textline_orientation: bool


# The two profiles differ in `use_doc_unwarping` only.
PROFILE_A = Profile(
    name="ppocrv6_vi_unwarp_on",
    lang="vi",
    ocr_version="PP-OCRv6",
    detection_model="PP-OCRv6_medium_det",
    recognition_model="PP-OCRv6_medium_rec",
    use_doc_orientation_classify=True,
    use_doc_unwarping=True,
    use_textline_orientation=True,
)
PROFILE_B = Profile(
    name="ppocrv6_vi_unwarp_off",
    lang="vi",
    ocr_version="PP-OCRv6",
    detection_model="PP-OCRv6_medium_det",
    recognition_model="PP-OCRv6_medium_rec",
    use_doc_orientation_classify=True,
    use_doc_unwarping=False,
    use_textline_orientation=True,
)
PROFILES = {profile.name: profile for profile in (PROFILE_A, PROFILE_B)}


def page_tag(page: int) -> str:
    return f"page_{page:04d}"


def page_number(tag: str) -> int:
    return int(tag.rsplit("_", 1)[1])


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(data)


def write_json(path: Path, data: object) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def read_page_text(path: Path) -> str:
    """Text of a page file as it is compared: lines joined by ``\\n``.

    A byte-order mark, the platform's line endings and the single newline that
    terminates the file are properties of the file, not of the page, and are
    dropped. Nothing else is touched.
    """
    with path.open(encoding="utf-8-sig") as stream:
        text = stream.read()
    return text[:-1] if text.endswith("\n") else text


def finished_documents(profile_dir: Path) -> list[str]:
    """Documents of a profile whose run completed (metadata.json is present)."""
    if not profile_dir.is_dir():
        return []
    return sorted(
        path.name
        for path in profile_dir.iterdir()
        if path.is_dir() and (path / "metadata.json").is_file()
    )


def load_page_lines(document_dir: Path) -> dict[int, list[dict]]:
    """Recognised lines per page number, including pages without any line."""
    metadata = read_json(document_dir / "metadata.json")
    pages: dict[int, list[dict]] = {entry["page"]: [] for entry in metadata["pages"]}
    with (document_dir / "lines.jsonl").open(encoding="utf-8") as stream:
        for row in stream:
            line = json.loads(row)
            pages[line["page"]].append(line)
    return pages


def lines_to_text(lines: list[dict]) -> str:
    """Page text of a prediction: recognised lines in pipeline order."""
    return "\n".join(line["text"] for line in lines)


def ground_truth_metadata_path(ground_truth_dir: Path, document: str) -> Path:
    return ground_truth_dir / document / "metadata.json"


def load_verified_ground_truth(
    ground_truth_dir: Path,
) -> tuple[dict[tuple[str, int], str], list[str]]:
    """Human-verified pages, plus the reasons other pages were left out.

    A page counts only if its metadata says ``verified: true`` *and* the file
    still has the SHA-256 recorded at verification. A page edited afterwards is
    skipped until it is verified again.
    """
    verified: dict[tuple[str, int], str] = {}
    skipped: list[str] = []
    if not ground_truth_dir.is_dir():
        return verified, skipped

    for document_dir in sorted(p for p in ground_truth_dir.iterdir() if p.is_dir()):
        metadata_path = document_dir / "metadata.json"
        pages = read_json(metadata_path)["pages"] if metadata_path.is_file() else {}
        for page_file in sorted(document_dir.glob("page_*.txt")):
            label = f"{document_dir.name}/{page_file.name}"
            entry = pages.get(page_file.stem)
            if not entry or entry.get("verified") is not True:
                skipped.append(f"{label}: not marked verified")
            elif entry.get("sha256") != sha256_file(page_file):
                skipped.append(f"{label}: changed after verification, verify it again")
            else:
                verified[(document_dir.name, page_number(page_file.stem))] = (
                    read_page_text(page_file)
                )
    return verified, skipped

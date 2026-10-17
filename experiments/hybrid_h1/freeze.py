"""Freeze candidate H1, the A0 pipeline it is compared with, the blind tools and the GO/NO-GO criteria.

Run from repo root (Windows CMD):
  .venv-demo\\Scripts\\python.exe -m experiments.hybrid_h1.freeze write --output-dir <new_dir> ^
    --preregistration <dir>\\h1_preregistration.json
  .venv-demo\\Scripts\\python.exe -m experiments.hybrid_h1.freeze verify --manifest <new_dir>\\freeze_manifest.json

``write`` records the SHA-256 of every file the candidate, the A0 pipeline and the
blind tools depend on (code, criteria, lexicon, recognizer and detector weights),
the gates and the library versions, and copies the frozen source files next to
the manifest. ``verify`` recomputes all of it and reports every difference;
every blind step refuses to run unless it passes.

Text files are hashed with CRLF line endings read as LF, so an LF and a CRLF
checkout of the same content verify alike; their raw-byte hashes are recorded
too, and a difference in line endings only is reported as a note. Weights are
hashed byte for byte. A missing file is a difference (the recognizer and
detector weights are not in git). A v1 manifest recorded raw bytes and is
compared on raw bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DETECTOR = Path.home() / ".paddlex" / "official_models" / "PP-OCRv6_medium_det"
FROZEN_FILES = {
    "candidate": ["experiments/hybrid_h1/__init__.py", "experiments/hybrid_h1/gates.py", "experiments/hybrid_h1/hybrid.py"],
    "criteria": ["experiments/hybrid_h1/blind_criteria_v1.json"],
    "evaluation_tools": ["experiments/hybrid_h1/evaluate_h1.py", "experiments/hybrid_h1/score_paired.py",
                         "experiments/hybrid_h1/blind.py", "experiments/hybrid_h1/freeze.py"],
    "tests": ["experiments/hybrid_h1/tests/__init__.py", "experiments/hybrid_h1/tests/test_gates.py",
              "experiments/hybrid_h1/tests/test_hybrid.py", "experiments/hybrid_h1/tests/test_evaluate_h1.py",
              "experiments/hybrid_h1/tests/test_score_paired.py", "experiments/hybrid_h1/tests/test_blind.py",
              "experiments/hybrid_h1/tests/test_freeze.py"],
    "reused_modules": ["demo/local_pdf_ocr/__init__.py", "demo/local_pdf_ocr/quality/__init__.py",
                       "demo/local_pdf_ocr/quality/gt_v2.py", "demo/local_pdf_ocr/quality/benchmark.py",
                       "demo/local_pdf_ocr/quality/vietdoc_review40.py", "demo/local_pdf_ocr/quality/error_analysis.py",
                       "demo/local_pdf_ocr/quality/e2e_regression.py", "experiments/crop_geometry/__init__.py",
                       "experiments/crop_geometry/evaluate.py"],
    "a0_pipeline": ["demo/local_pdf_ocr/backend/__init__.py", "demo/local_pdf_ocr/backend/engine.py",
                    "demo/local_pdf_ocr/backend/contract.py", "demo/local_pdf_ocr/backend/header_split.py",
                    "demo/local_pdf_ocr/backend/ocr_layout_v2.py"],
    "reference_data": ["datasets/vietnamese_recognition/lexicon/administrative.txt",
                       "datasets/vietnamese_recognition/manifests/hard_cases.txt"],
    "models": ["models/vietocr/onnx/exp_b_width1024/metadata.json", "models/vietocr/onnx/exp_b_width1024/encoder.onnx",
               "models/vietocr/onnx/exp_b_width1024/decoder_step.onnx"],
}
DETECTOR_FILES = ["inference.json", "inference.pdiparams", "inference.yml"]
LIBRARIES = ("pymupdf", "numpy", "pillow", "onnxruntime", "paddlex", "paddlepaddle", "opencv-contrib-python", "opencv-python")
COPIED_GROUPS = ("candidate", "criteria", "evaluation_tools", "tests", "reused_modules", "a0_pipeline", "reference_data")
SCHEMA = "h1_freeze_manifest_v2"
TEXT_SUFFIXES = (".json", ".py", ".txt", ".yml")
HASHING = {"text_files": "sha256 of the bytes with every CRLF replaced by LF", "other_files": "sha256 of the raw bytes",
           "text_suffixes": list(TEXT_SUFFIXES), "raw_sha256": "raw-byte sha256 of the text files, for information"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def is_text(path) -> bool:
    return Path(path).suffix.lower() in TEXT_SUFFIXES


def sha256_lf(path: Path) -> str:
    """SHA-256 of a text file with CRLF read as LF: an LF and a CRLF checkout of it agree."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def frozen_sha256(path: Path) -> str | None:
    """The hash a v2 manifest records: CRLF read as LF for text files, raw bytes otherwise; None if missing."""
    path = Path(path)
    if not path.is_file():
        return None
    return sha256_lf(path) if is_text(path) else sha256_file(path)


def library_versions() -> dict[str, str | None]:
    versions = {"python": platform.python_version()}
    for name in LIBRARIES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def current_state() -> dict:
    from .gates import GATES
    from .hybrid import gates_sha256

    paths = {group: {path: REPO / path for path in paths} for group, paths in FROZEN_FILES.items()}
    paths["detector"] = {f"~/.paddlex/official_models/PP-OCRv6_medium_det/{name}": DETECTOR / name for name in DETECTOR_FILES}
    files = {group: {key: frozen_sha256(path) for key, path in items.items()} for group, items in paths.items()}
    raw = {group: {key: sha256_file(path) for key, path in items.items() if is_text(path) and path.is_file()}
           for group, items in paths.items()}
    metadata_path = REPO / "models/vietocr/onnx/exp_b_width1024/metadata.json"
    model = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else None
    return {"hashing": HASHING, "files": files, "raw_sha256": raw, "gates": GATES, "gates_sha256": gates_sha256(),
            "libraries": library_versions(),
            "b1024": model and {k: model[k] for k in ("selected", "checkpoint_sha256", "encoder_sha256", "decoder_sha256", "config_sha256")}}


def raw_hashes(state: dict) -> dict:
    """Raw-byte hash of every file of a state: text files have their own, the others are hashed raw already."""
    return {group: {path: state["raw_sha256"].get(group, {}).get(path, digest) for path, digest in files.items()}
            for group, files in state["files"].items()}


def compare(recorded: dict, now: dict) -> list[str]:
    problems = []
    current = raw_hashes(now) if recorded.get("schema") == "h1_freeze_manifest_v1" else now["files"]
    for group, files in recorded["files"].items():
        for path, digest in files.items():
            found = current.get(group, {}).get(path)
            if found != digest:
                problems.append(f"{group}: {path} {'is missing' if found is None else 'differs'}")
    for key in ("gates_sha256", "libraries", "b1024"):
        if recorded[key] != now[key]:
            problems.append(f"{key} differs: {recorded[key]} -> {now[key]}")
    models, model = now["files"]["models"], now["b1024"]
    if model and (models["models/vietocr/onnx/exp_b_width1024/encoder.onnx"] != model["encoder_sha256"] or
                  models["models/vietocr/onnx/exp_b_width1024/decoder_step.onnx"] != model["decoder_sha256"]):
        problems.append("ONNX files do not match the model metadata")
    return problems


def line_ending_notes(recorded: dict, now: dict) -> list[str]:
    """Text files whose content is frozen but whose line endings differ from those at freeze time."""
    notes = []
    for group, files in recorded.get("raw_sha256", {}).items():
        for path, digest in files.items():
            found = now["raw_sha256"].get(group, {}).get(path)
            if found not in (None, digest) and now["files"].get(group, {}).get(path) == recorded["files"][group][path]:
                notes.append(f"{group}: {path} has other line endings than at freeze time; its content is frozen")
    return notes


def write(output_dir: Path, preregistration: Path) -> dict:
    if output_dir.exists():
        raise ValueError(f"STOP: will not overwrite {output_dir}")
    state = current_state()
    problems = compare(state, state) + [f"{group}: {path} is missing" for group, files in state["files"].items()
                                        for path, digest in files.items() if digest is None]
    if problems or state["b1024"] is None:
        raise ValueError(f"STOP: the current files are inconsistent or incomplete: {problems or ['no model metadata']}")
    prereg = json.loads(preregistration.read_text(encoding="utf-8"))
    # The registration hashed the LF files byte for byte, which is also their v2 hash.
    candidate = state["files"]["candidate"]
    if (candidate["experiments/hybrid_h1/gates.py"] != prereg["code_sha256"]["gates.py"]
            or candidate["experiments/hybrid_h1/hybrid.py"] != prereg["code_sha256"]["hybrid.py"]
            or state["gates_sha256"] != prereg["gates_sha256"]):
        raise ValueError("STOP: the candidate differs from its 2026-10-16 registration")
    output_dir.mkdir(parents=True)
    for group in COPIED_GROUPS:
        for path in FROZEN_FILES[group]:
            target = output_dir / "source" / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / path, target)
    manifest = {
        "schema": SCHEMA, "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "candidate": "h1_v1", "candidate_registered_at": prereg["registered_at"],
        "preregistration_sha256": sha256_file(preregistration),
        "blind_labels_existing_at_freeze": "none", "blind_documents_registered_at_freeze": "none",
        **state,
        "criteria": json.loads((REPO / FROZEN_FILES["criteria"][0]).read_text(encoding="utf-8")),
        "rule": "blind steps run only while `freeze verify` reports no difference; any change makes a new candidate",
    }
    path = output_dir / "freeze_manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return {"manifest": str(path), "manifest_sha256": sha256_lf(path),
            "files": sum(len(f) for f in state["files"].values())}


def verify(manifest_path: Path) -> dict:
    """The manifest's own hash (which a blind round is bound to) reads CRLF as LF, like any text file."""
    recorded = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    now = current_state()
    problems = compare(recorded, now)
    return {"ok": not problems, "problems": problems, "notes": line_ending_notes(recorded, now),
            "manifest_sha256": sha256_lf(manifest_path)}


def require(manifest_path: Path) -> dict:
    """Stop unless the freeze holds; returns the frozen manifest."""
    result = verify(manifest_path)
    if not result["ok"]:
        raise ValueError(f"STOP: the H1 freeze does not hold: {result['problems']}")
    return json.loads(Path(manifest_path).read_text(encoding="utf-8")) | {"_manifest_sha256": result["manifest_sha256"]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    w = commands.add_parser("write")
    w.add_argument("--output-dir", type=Path, required=True)
    w.add_argument("--preregistration", type=Path, required=True)
    v = commands.add_parser("verify")
    v.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    result = write(args.output_dir, args.preregistration) if args.command == "write" else verify(args.manifest)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())

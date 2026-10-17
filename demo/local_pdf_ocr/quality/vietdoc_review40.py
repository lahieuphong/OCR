"""Label QA and reproducible baseline evaluation for the VietDoc 5-PDF review pack.

Run from repo root (Windows CMD):
  .venv-demo\\Scripts\\python.exe -m demo.local_pdf_ocr.quality.vietdoc_review40 evaluate ^
    --pack-dir vietdoc_5pdf_quality_review_40 ^
    --labels "<LABELS_DIR>\\vietdoc_5pdf_verified_labels.json" ^
    --pdf-dir "<SAMPLES_DIR>" ^
    --recheck <ID> --recheck <ID> ^
    --output-dir demo\\local_pdf_ocr\\quality_work\\<new_eval_dir>

``evaluate`` is model-free. It reads the pack manifest, the offline review
HTML, the downloaded labels, the crop PNGs and, when PyMuPDF is installed,
the source PDFs' embedded text layer. It writes label_integrity_report.json,
manual_recheck_required.csv and baseline_metrics.json; with
``--candidate PREDICTIONS.jsonl`` ({"id", "prediction"} per line) it also
writes candidate_comparison.json.

``parity`` loads the frozen VietOCR B ONNX, re-derives every crop from its
PDF and polygon with PaddleX CropByPolys, and checks that the pack crops and
the stored OCR text are reproduced exactly. It is evidence, not a baseline.

Nothing here edits labels, crops, PDFs or OCR exports, reruns detection,
corrects text with a dictionary, reads blind-test labels, or writes over an
existing report. Labels with an open recheck item are kept out of the trusted
set; uncertain labels are never scored. Scores on 40 selected lines are NOT
whole-document or whole-system CER.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import subprocess
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from .benchmark import distance, metrics, nfc, read_jsonl, sha256
from .error_analysis import difference_tags, edits

REPO_ROOT = Path(__file__).resolve().parents[3]
LABEL_SCHEMA = "vietdoc_holdout_manual_review_v1"
GROUPS = ("representative_hash_selected", "diagnostic_targeted")
REGIONS = ("printed_text", "handwriting", "stamp_overlap", "stamp_artifact", "uncertain")
COPIED_FIELDS = ("document", "pdf_sha256", "source_ocr_json_sha256", "page", "line_index",
                 "image_sha256", "sample_group", "ocr_original")
# Preliminary baseline figures this evaluation must reconcile.
PRELIMINARY = {"verified": 39, "uncertain": 1, "exact": 33, "mismatch": 6, "cer": 0.00485, "wer": 0.01948}
MAX_IMAGE_PIXELS = 12_000_000  # same page raster rule as backend.engine.iter_images
LEXICON = REPO_ROOT / "datasets/vietnamese_recognition/lexicon/administrative.txt"
AGENCY_SECTIONS = ("agency", "department", "unit")
# Party and generic bodies missing from the public lexicon above.
AGENCY_EXTRA = ("Bộ Chính trị", "Đảng ủy Chính phủ", "Đảng ủy", "Ủy ban nhân dân", "UBND")
HARD_CASES = REPO_ROOT / "datasets/vietnamese_recognition/manifests/hard_cases.txt"
# Non-blind transcripts only; blind_test.tsv is never opened.
CORPUS = tuple(REPO_ROOT / "datasets/vietnamese_recognition/manifests" / name for name in (
    "real_train.tsv", "real_val.tsv", "synthetic_train.tsv", "synthetic_val.tsv", "bakeoff_regression.tsv"))
CORPUS_MIN_VARIANT = 3
# Training labels carry the same accepted-OCR slips (one "quy đinh" in
# real_train.tsv), so a rare form is flagged when its variant is far commoner.
CORPUS_RATIO = 20
MODEL_METADATA = REPO_ROOT / "models/vietocr/onnx/exp_b_width1024/metadata.json"
OCR_CODE = ("demo/local_pdf_ocr/backend/engine.py", "demo/local_pdf_ocr/backend/header_split.py",
            "demo/local_pdf_ocr/backend/contract.py", "demo/local_pdf_ocr/backend/ocr_layout_v2.py")
OUTPUTS = ("label_integrity_report.json", "manual_recheck_required.csv", "baseline_metrics.json")
BOOTSTRAP_DRAWS, BOOTSTRAP_SEED = 10_000, 20261016

TONES = {"̀": "huyen", "́": "sac", "̃": "nga", "̉": "hoi", "̣": "nang"}
SHAPES = {"̂": "circumflex", "̆": "breve", "̛": "horn"}
ZERO_O_Q = frozenset("0OoQq")
INVISIBLE = re.compile(r"[​-‏ -‮⁠-⁤﻿­]")


# ---------------------------------------------------------------- loading

def parse_html_pack(path: Path) -> dict:
    """The PACK object embedded in the offline review page."""
    text = path.read_text(encoding="utf-8")
    marker = "const PACK="
    start = text.find(marker)
    if start < 0:
        raise ValueError(f"STOP: no embedded PACK in {path.name}")
    pack, _ = json.JSONDecoder().raw_decode(text, start + len(marker))
    return pack


def png_sha256(data_uri: str) -> str:
    import base64
    import hashlib

    return hashlib.sha256(base64.b64decode(data_uri.split(",", 1)[1])).hexdigest()


# ------------------------------------------------- characters and alignment

def decompose(character: str) -> tuple[str, str | None, str | None]:
    """(base letter, vowel/consonant modifier, tone) of one character."""
    if character in "đĐ":
        return ("d" if character == "đ" else "D"), "stroke", None
    parts = unicodedata.normalize("NFD", character)
    base, shape, tone = parts[:1], None, None
    for mark in parts[1:]:
        if mark in TONES:
            tone = TONES[mark]
        elif mark in SHAPES:
            shape = SHAPES[mark]
        else:
            base += mark
    return base, shape, tone


def skeleton(word: str) -> str:
    """Word without any tone, modifier or đ stroke."""
    return "".join(decompose(c)[0] for c in nfc(word).lower())


def tone_key(word: str) -> tuple[str, str | None]:
    """Placement-invariant identity: hoá and hóa share (letters+modifiers, tone)."""
    letters, tone = [], None
    for character in nfc(word).lower():
        parts = unicodedata.normalize("NFD", character)
        letters.append("".join(m for m in parts if m not in TONES))
        tone = next((TONES[m] for m in parts if m in TONES), tone)
    return nfc("".join(letters)), tone


def alignment(reference, hypothesis) -> list[tuple[str, int, int]]:
    """Minimal Levenshtein edit script as (operation, ref_index, hyp_index).

    For ``delete``/``insert`` the index that does not apply is the position
    the edit happens at. Ties prefer substitution, then deletion.
    """
    rows, columns = len(reference) + 1, len(hypothesis) + 1
    table = [[0] * columns for _ in range(rows)]
    for i in range(rows):
        table[i][0] = i
    for j in range(columns):
        table[0][j] = j
    for i in range(1, rows):
        for j in range(1, columns):
            table[i][j] = min(table[i - 1][j - 1] + (reference[i - 1] != hypothesis[j - 1]),
                              table[i - 1][j] + 1, table[i][j - 1] + 1)
    steps, i, j = [], len(reference), len(hypothesis)
    while i > 0 or j > 0:
        if i > 0 and j > 0 and table[i][j] == table[i - 1][j - 1] + (reference[i - 1] != hypothesis[j - 1]):
            steps.append(("equal" if reference[i - 1] == hypothesis[j - 1] else "substitute", i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i > 0 and table[i][j] == table[i - 1][j] + 1:
            steps.append(("delete", i - 1, j))
            i -= 1
        else:
            steps.append(("insert", i, j - 1))
            j -= 1
    steps.reverse()
    return steps


def pair_details(reference: str, hypothesis: str) -> list[str]:
    """Labels for one substituted character pair; describes, never explains."""
    rb, rs, rt = decompose(reference)
    hb, hs, ht = decompose(hypothesis)
    labels = []
    if rb.casefold() == hb.casefold() and rb.isalpha():
        if (rs, rt) != (hs, ht):
            labels.append("diacritic")
            if rt and not ht:
                labels.append(f"tone_dropped:{rt}")
            elif ht and not rt:
                labels.append(f"tone_added:{ht}")
            elif rt != ht:
                labels.append(f"tone_changed:{rt}->{ht}")
            if rs and not hs:
                labels.append(f"modifier_dropped:{rs}")
            elif hs and not rs:
                labels.append(f"modifier_added:{hs}")
            elif rs != hs:
                labels.append(f"modifier_changed:{rs}->{hs}")
        if rb != hb:
            labels.append("case")
    elif reference in ZERO_O_Q and hypothesis in ZERO_O_Q:
        labels.append("zero_O_Q")
    elif {reference, hypothesis} in ({"1", "U"}, {"1", "u"}):
        labels.append("one_U")
    else:
        labels.append("substitution_other")
    return labels


def error_spans(reference: str, hypothesis: str) -> list[dict]:
    """Contiguous non-equal runs of the minimal alignment, with categories."""
    ref, hyp = nfc(reference), nfc(hypothesis)
    runs, current = [], None
    for operation, i, j in alignment(ref, hyp):
        if operation == "equal":
            if current:
                runs.append(current)
                current = None
            continue
        if current is None:
            current = {"ref_start": i, "ref_end": i, "hyp_start": j, "hyp_end": j, "ops": []}
        current["ops"].append((operation, i, j))
        if operation in ("substitute", "delete"):
            current["ref_end"] = i + 1
        if operation in ("substitute", "insert"):
            current["hyp_end"] = j + 1
    if current:
        runs.append(current)
    spans = []
    for run in runs:
        reference_text = ref[run["ref_start"]:run["ref_end"]]
        hypothesis_text = hyp[run["hyp_start"]:run["hyp_end"]]
        details = []
        for operation, i, j in run["ops"]:
            if operation == "substitute":
                details += pair_details(ref[i], hyp[j])
            else:
                details.append(operation)
        categories = {d.split(":")[0] for d in details}
        if set(reference_text) & ZERO_O_Q and set(hypothesis_text) & ZERO_O_Q and reference_text != hypothesis_text:
            categories.add("zero_O_Q")
        if ("1" in reference_text and set(hypothesis_text) & {"U", "u"}) or (
                "1" in hypothesis_text and set(reference_text) & {"U", "u"}):
            categories.add("one_U")
        if any(c.isdigit() for c in reference_text + hypothesis_text):
            categories.add("digit")
        if any(unicodedata.category(c).startswith("P") for c in reference_text + hypothesis_text):
            categories.add("punctuation")
        if any(c.isspace() for c in reference_text + hypothesis_text):
            categories.add("spacing")
        spans.append({
            "ref_start": run["ref_start"], "ref_end": run["ref_end"],
            "reference": reference_text, "hypothesis": hypothesis_text,
            "cost": len(run["ops"]), "categories": sorted(categories), "details": details,
        })
    return spans


# --------------------------------------------------------- entity tagging

def lexicon_sections(path: Path = LEXICON) -> dict[str, list[str]]:
    sections, current = defaultdict(list), None
    if not path.is_file():
        return {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
        elif current:
            sections[current].append(line)
    return dict(sections)


def agency_names(path: Path = LEXICON) -> list[str]:
    sections = lexicon_sections(path)
    names = {nfc(n) for s in AGENCY_SECTIONS for n in sections.get(s, [])} | {nfc(n) for n in AGENCY_EXTRA}
    return sorted(names, key=len, reverse=True)


def entity_spans(reference: str, agencies: list[str]) -> list[dict]:
    """Document numbers, e-mail addresses and agency names in the REFERENCE text."""
    ref = nfc(reference)
    spans = []
    for match in re.finditer(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", ref):
        spans.append({"type": "email", "start": match.start(), "end": match.end()})
    for match in re.finditer(r"\S+", ref):
        token = match.group().lstrip("(").rstrip(";,.:)")
        start = match.start() + match.group().index(token) if token else match.start()
        if ("/" in token and re.fullmatch(r"[0-9A-Za-zĐđ./-]+", token)
                and re.search(r"[A-ZĐ]", token) and "@" not in token):
            spans.append({"type": "doc_number", "start": start, "end": start + len(token)})
    lowered = ref.lower()
    if len(lowered) == len(ref):
        covered = []
        for name in agencies:
            needle = name.lower()
            for match in re.finditer(re.escape(needle), lowered):
                a, b = match.start(), match.end()
                before = lowered[a - 1] if a else " "
                after = lowered[b] if b < len(lowered) else " "
                if before.isalnum() or after.isalnum() or any(a < e and b > s for s, e in covered):
                    continue
                covered.append((a, b))
        spans += [{"type": "agency_name", "start": a, "end": b} for a, b in sorted(covered)]
    for span in spans:
        span["text"] = ref[span["start"]:span["end"]]
    return sorted(spans, key=lambda s: (s["start"], s["type"]))


def overlaps(span: dict, entity: dict) -> bool:
    start, end = span["ref_start"], span["ref_end"]
    if end == start:  # pure insertion at a reference position
        return entity["start"] <= start <= entity["end"]
    return start < entity["end"] and end > entity["start"]


# ------------------------------------------------------ corpus evidence

def corpus_counts(paths=None) -> tuple[Counter, dict, list[str]]:
    """Bigram counts keyed by placement-invariant word keys, with display forms."""
    counts, display, used = Counter(), {}, []
    for path in CORPUS if paths is None else paths:
        if path.name == "blind_test.tsv":
            raise ValueError("STOP: blind-test transcripts are never used")
        if not path.is_file():
            continue
        used.append(path.name)
        with path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream, delimiter="\t"):
                words = re.findall(r"[^\W\d_]+", nfc(row.get("text") or row.get("ground_truth") or ""))
                for a, b in zip(words, words[1:]):
                    key = (tone_key(a), tone_key(b))
                    counts[key] += 1
                    display.setdefault(key, f"{a.lower()} {b.lower()}")
    return counts, display, used


def skeleton_index(counts: Counter) -> dict:
    """Corpus bigram keys grouped by their diacritic-free skeleton."""
    index = defaultdict(list)
    for key, amount in counts.items():
        index[(skeleton(key[0][0]), skeleton(key[1][0]))].append((amount, key))
    return index


def corpus_variant_flags(reference: str, counts: Counter, display: dict, index: dict) -> list[dict]:
    """Bigrams that are rare in the corpus while a diacritic variant is common.

    A flag is a request for a human to look again, never a correction.
    """
    flags = []
    words = re.findall(r"[^\W\d_]+", nfc(reference))
    for a, b in zip(words, words[1:]):
        key = (tone_key(a), tone_key(b))
        seen = counts.get(key, 0)
        variants = [(n, k) for n, k in index.get((skeleton(a), skeleton(b)), []) if k != key]
        if variants:
            amount, best = max(variants, key=lambda item: item[0])
            if amount >= max(CORPUS_MIN_VARIANT, CORPUS_RATIO * seen):
                flags.append({"bigram": f"{a} {b}", "corpus_count": seen,
                              "common_variant": display[best], "variant_count": amount})
    return flags


def hard_case_entries(path: Path = HARD_CASES) -> list[str]:
    if not path.is_file():
        return []
    entries = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    return [nfc(e.lower()) for e in entries if e and not e.startswith("#") and re.search(r"[^\W\d_]", e)]


# ------------------------------------------------------------- hygiene

def text_hygiene(text: str, vocabulary: set[str] | None) -> list[str]:
    issues = []
    if text != nfc(text):
        issues.append("not_nfc")
    if INVISIBLE.search(text) or any(unicodedata.category(c) == "Cc" for c in text):
        issues.append("invisible_or_control_character")
    if text != text.strip():
        issues.append("leading_or_trailing_whitespace")
    if "  " in text:
        issues.append("double_space")
    if "\n" in text or "\r" in text:
        issues.append("multiple_lines")
    if vocabulary is not None:
        missing = sorted({c for c in nfc(text) if c not in vocabulary})
        if missing:
            issues.append("outside_recognizer_vocab:" + "".join(missing))
    return issues


def recognizer_vocabulary(path: Path = MODEL_METADATA) -> set[str] | None:
    try:
        return set(json.loads(path.read_text(encoding="utf-8"))["vocab"])
    except (OSError, ValueError, KeyError):
        return None


# ------------------------------------------------------------ PDF evidence

def page_zoom(width: float, height: float) -> float:
    return min(2.0, math.sqrt(MAX_IMAGE_PIXELS / (width * height)))


def pdf_evidence(pdf_path: Path, samples: list[dict]) -> dict:
    """Page geometry and embedded text inside each sample polygon (PyMuPDF)."""
    import fitz

    result = {"pages": None, "samples": {}}
    with fitz.open(pdf_path) as pdf:
        result["pages"] = len(pdf)
        for sample in samples:
            if not 1 <= sample["page"] <= len(pdf):
                result["samples"][sample["id"]] = {"page_in_range": False}
                continue
            page = pdf[sample["page"] - 1]
            zoom = page_zoom(page.rect.width, page.rect.height)
            width, height = round(page.rect.width * zoom), round(page.rect.height * zoom)
            xs = [p[0] for p in sample["polygon"]]
            ys = [p[1] for p in sample["polygon"]]
            x0, x1, y0, y1 = min(xs) / zoom, max(xs) / zoom, min(ys) / zoom, max(ys) / zoom
            words = [w for w in page.get_text("words", sort=False)
                     if x0 <= (w[0] + w[2]) / 2 <= x1 and y0 <= (w[1] + w[3]) / 2 <= y1]
            words.sort(key=lambda w: (w[5], w[6], w[7]))
            result["samples"][sample["id"]] = {
                "page_in_range": True,
                "raster_size": [width, height],
                "polygon_inside_raster": min(xs) >= 0 and min(ys) >= 0 and max(xs) <= width and max(ys) <= height,
                "page_text_chars": len(page.get_text("text")),
                "page_fonts": len(page.get_fonts()),
                "text_layer_words": len(words),
                "text_layer": nfc(" ".join(w[4] for w in words)) if words else None,
            }
    return result


# ----------------------------------------------------------------- audit

def check(name: str, status: str, detail) -> dict:
    return {"check": name, "status": status, "detail": detail}


def git_state(repo: Path = REPO_ROOT) -> dict:
    def run(*args):
        try:
            # rstrip only: porcelain status lines start with a meaningful space.
            return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                                  encoding="utf-8", timeout=120, check=True).stdout.rstrip()
        except (OSError, subprocess.SubprocessError):
            return None

    status = run("status", "--porcelain=v1", "--untracked-files=normal")
    behind = run("rev-list", "--left-right", "--count", "HEAD...@{u}")
    return {
        "branch": run("branch", "--show-current"),
        "head": run("rev-parse", "HEAD"),
        "head_subject": run("log", "-1", "--format=%s"),
        "upstream": run("rev-parse", "--abbrev-ref", "@{u}"),
        "ahead_behind_upstream": behind.split() if behind else None,
        "main": run("rev-parse", "main"),
        "status_counts": dict(Counter(line[:2] for line in status.splitlines())) if status else None,
        "content_diff_unstaged_files": len((run("diff", "--name-only") or "").splitlines()),
        "ocr_code_blob_sha1": {path: run("hash-object", path) for path in OCR_CODE},
        "note": "No fetch was performed; ahead/behind reflects the last fetch. Read-only.",
    }


def model_state() -> dict:
    from demo.local_pdf_ocr.backend import contract

    files = {
        "encoder.onnx": (contract.MODEL_DIR / "encoder.onnx", contract.EXPECTED_ENCODER_SHA256),
        "decoder_step.onnx": (contract.MODEL_DIR / "decoder_step.onnx", contract.EXPECTED_DECODER_SHA256),
        "weights.pth": (contract.WEIGHTS, contract.CHECKPOINT_SHA256),
    }
    state = {}
    for name, (path, expected) in files.items():
        actual = sha256(path) if path.is_file() else None
        state[name] = {"sha256": actual, "expected": expected, "match": actual == expected}
    return state


class Recheck:
    """Open questions per label. A ``high`` item keeps the label out of the trusted set;
    ``medium`` screen hits are listed for a human but do not by themselves quarantine."""

    def __init__(self):
        self.items = defaultdict(list)

    def add(self, identifier: str, code: str, priority: str, question: str, evidence: str = "") -> None:
        self.items[identifier].append({"code": code, "priority": priority, "question": question,
                                       "evidence": evidence})

    def quarantines(self, identifier: str) -> bool:
        return any(item["priority"] == "high" for item in self.items.get(identifier, []))


def review(row: dict) -> dict:
    return row.get("review", {})


def contract_checks(labels: dict, manifest: dict, pack: dict | None) -> list[dict]:
    problems = [k for k, v in (("schema", LABEL_SCHEMA), ("model_inference_performed", False),
                               ("blind_test_used", False), ("auto_replace_approved", False))
                if labels.get(k) != v]
    manifest_problems = [k for k, v in (("status", "REVIEW_PACK_UNLABELED"), ("no_ground_truth_included", True),
                                        ("blind_test_used", False), ("ocr_baseline_unchanged", True))
                         if manifest.get(k) != v]
    checks = [
        check("labels_top_level_contract", "FAIL" if problems else "PASS",
              {"schema": labels.get("schema"), "status": labels.get("status"),
               "generated_at": labels.get("generated_at"), "violations": problems}),
        check("manifest_contract", "FAIL" if manifest_problems else "PASS",
              {"selection": manifest.get("selection"), "violations": manifest_problems}),
    ]
    if pack is None:
        checks.append(check("review_html_binding", "BLOCKED", "mo_review_40.html missing"))
    else:
        bound = labels.get("pack_sha256") == pack.get("pack_id")
        checks.append(check("review_html_binding", "PASS" if bound else "FAIL",
                            {"labels_pack_sha256": labels.get("pack_sha256"), "html_pack_id": pack.get("pack_id")}))
    return checks


def id_checks(manifest: dict, rows: list[dict], pack: dict | None) -> list[dict]:
    """IDs unique, paired and named by convention; copied fields equal the manifest."""
    samples = manifest.get("samples", [])
    by_id = {s["id"]: s for s in samples}
    duplicate_labels = [i for i, n in Counter(r["id"] for r in rows).items() if n > 1]
    duplicate_samples = [i for i, n in Counter(s["id"] for s in samples).items() if n > 1]
    unpaired = sorted(set(by_id) ^ {r["id"] for r in rows})
    bad_names = [s["id"] for s in samples
                 if s["id"] != f"{Path(s['document']).stem}__p{s['page']:03d}_l{s['line_index']:03d}"]
    ok = not (duplicate_labels or duplicate_samples or unpaired or bad_names) and len(samples) == manifest.get("count")
    field_mismatch = [{"id": r["id"], "field": f} for r in rows if r["id"] in by_id
                      for f in COPIED_FIELDS if r.get(f) != by_id[r["id"]].get(f)]
    checks = [
        check("ids_unique_paired_and_named", "PASS" if ok else "FAIL", {
            "manifest_count": manifest.get("count"), "samples": len(samples), "labels": len(rows),
            "duplicate_label_ids": duplicate_labels, "duplicate_sample_ids": duplicate_samples,
            "unpaired_ids": unpaired, "id_convention_violations": bad_names,
            "same_order": [s["id"] for s in samples] == [r["id"] for r in rows]}),
        check("label_fields_match_manifest", "FAIL" if field_mismatch else "PASS", field_mismatch),
    ]
    if pack is not None:
        html_rows = {r["id"]: r for r in pack.get("rows", [])}
        mismatch = [{"id": i, "field": f} for i, s in by_id.items() for f in (*COPIED_FIELDS, "polygon")
                    if i in html_rows and html_rows[i].get(f) != s.get(f)]
        mismatch += [{"id": i, "field": "missing_in_html"} for i in by_id if i not in html_rows]
        checks.append(check("html_rows_match_manifest", "FAIL" if mismatch else "PASS", mismatch))
    return checks


def review_state_check(labels: dict, rows: list[dict]) -> dict:
    problems = []
    for r in rows:
        state, reference = review(r).get("status"), review(r).get("reference")
        if state not in ("verified", "uncertain") or review(r).get("region") not in REGIONS:
            problems.append({"id": r["id"], "problem": "unknown_status_or_region"})
        if review(r).get("original_ocr_unchanged") is not True:
            problems.append({"id": r["id"], "problem": "original_ocr_changed"})
        if state == "verified" and (not isinstance(reference, str) or not reference.strip()
                                    or review(r).get("verified_by_human") is not True):
            problems.append({"id": r["id"], "problem": "verified_without_human_reference"})
        if state == "uncertain" and (reference is not None or review(r).get("verified_by_human")):
            problems.append({"id": r["id"], "problem": "uncertain_with_reference"})
    recount = Counter(review(r).get("status") for r in rows)
    declared = labels.get("summary", {})
    consistent = (declared.get("total") == len(rows) and declared.get("verified") == recount.get("verified", 0)
                  and declared.get("uncertain") == recount.get("uncertain", 0))
    return check("review_states", "FAIL" if problems or not consistent else "PASS",
                 {"declared_summary": declared, "recount": dict(recount), "problems": problems})


def hygiene_check(rows: list[dict], recheck: Recheck) -> dict:
    vocabulary = recognizer_vocabulary()
    found = {}
    for r in rows:
        reference = review(r).get("reference")
        if not isinstance(reference, str):
            continue
        issues = text_hygiene(reference, vocabulary)
        if issues:
            found[r["id"]] = issues
        # Out-of-vocab characters can be correct truth; only format issues reopen a label.
        formatting = [i for i in issues if not i.startswith("outside_recognizer_vocab")]
        if formatting:
            recheck.add(r["id"], "reference_hygiene", "medium",
                        "Kiểm tra định dạng nhãn (khoảng trắng/ký tự ẩn/Unicode): " + ", ".join(formatting))
    return check("reference_text_hygiene", "WARN" if found else "PASS",
                 {"vocab_available": vocabulary is not None, "issues": found})


def crop_checks(pack_dir: Path, samples: list[dict], pack: dict | None) -> tuple[list[dict], dict]:
    """Crop on disk inside the pack, hash, decodable, and identical to the HTML copy."""
    from PIL import Image

    rows, problems = {}, []
    root = pack_dir.resolve()
    embedded = {r["id"]: r.get("image_data") for r in pack.get("rows", [])} if pack else {}
    for s in samples:
        path = (pack_dir / s["image_file"]).resolve()
        record = {"exists": path.is_file() and root in path.parents}
        if record["exists"]:
            record["sha256_match"] = sha256(path) == s["image_sha256"]
            try:
                with Image.open(path) as image:
                    record["size"] = list(image.size)
            except Exception as error:  # noqa: BLE001 - reported, not hidden
                record["decode_error"] = type(error).__name__
            xs, ys = [p[0] for p in s["polygon"]], [p[1] for p in s["polygon"]]
            record["polygon_size"] = [max(xs) - min(xs), max(ys) - min(ys)]
        if embedded.get(s["id"]):
            record["html_image_sha256_match"] = png_sha256(embedded[s["id"]]) == s["image_sha256"]
        rows[s["id"]] = record
        if (not record["exists"] or not record.get("sha256_match") or "decode_error" in record
                or record.get("html_image_sha256_match") is False):
            problems.append(s["id"])
    sized = [r for r in rows.values() if r.get("size")]
    for r in sized:
        r["margin_vs_polygon_wh"] = [r["size"][0] - r["polygon_size"][0], r["size"][1] - r["polygon_size"][1]]
    small = {i: r["size"] for i, r in rows.items() if r.get("size") and min(r["size"]) < 12}
    margins = [r["margin_vs_polygon_wh"] for r in sized]
    padded = sum(1 for w, h in margins if w > 4 or h > 4)
    return [
        check("crop_files_and_hashes", "FAIL" if problems else "PASS", {"checked": len(samples), "problems": problems}),
        check("crop_geometry", "WARN" if small or padded else "PASS", {
            "crops_smaller_than_12px": small,
            "crops_larger_than_polygon_by_over_4px": padded,
            "margin_width_min_max": [min(m[0] for m in margins), max(m[0] for m in margins)] if margins else None,
            "margin_height_min_max": [min(m[1] for m in margins), max(m[1] for m in margins)] if margins else None,
            "note": "Review crops that include context around the polygon are NOT the recognizer input; "
                    "re-derive crops from PDF + polygon (parity --export-crops) before running a candidate."}),
    ], rows


def group_check(manifest: dict) -> dict:
    documents = {d["document"]: d for d in manifest.get("documents", [])}
    per_document = defaultdict(Counter)
    for s in manifest.get("samples", []):
        per_document[s["document"]][s["sample_group"]] += 1
    problems = [doc for doc, c in per_document.items()
                if doc not in documents or set(c) - set(GROUPS)
                or c["representative_hash_selected"] != documents[doc].get("representative")
                or c["diagnostic_targeted"] != documents[doc].get("diagnostic")]
    return check("sample_groups", "FAIL" if problems else "PASS", {
        "per_document": {d: dict(c) for d, c in per_document.items()}, "problems": problems,
        "warning": "Groups must not be pooled into a representative CER."})


def pdf_check(manifest: dict, pdf_dir: Path | None) -> tuple[dict, dict]:
    """Source PDF hash, page count and polygon geometry; returns per-sample evidence too."""
    records, evidence = {}, {}
    for info in manifest.get("documents", []):
        document = info["document"]
        record = {"expected_sha256": info.get("pdf_sha256"), "path": None}
        path = pdf_dir / document if pdf_dir else None
        if path is None or not path.is_file():
            record["status"] = "BLOCKED_MISSING"
        else:
            record["path"] = str(path)
            record["sha256_match"] = sha256(path) == info.get("pdf_sha256")
            try:
                found = pdf_evidence(path, [s for s in manifest["samples"] if s["document"] == document])
            except ImportError:
                record["status"] = "HASH_ONLY_NO_PYMUPDF"
            else:
                record["pages"] = found["pages"]
                record["page_count_match"] = found["pages"] == info.get("pages")
                evidence.update(found["samples"])
                record["status"] = "PASS" if record["sha256_match"] and record["page_count_match"] else "FAIL"
        records[document] = record
    geometry = [i for i, e in evidence.items() if not e.get("page_in_range") or not e.get("polygon_inside_raster")]
    statuses = {r["status"] for r in records.values()}
    status = ("BLOCKED" if "BLOCKED_MISSING" in statuses else
              "FAIL" if "FAIL" in statuses or geometry else "PASS")
    return check("source_pdfs", status, {"documents": records, "geometry_problems": geometry}), evidence


def ocr_json_check(manifest: dict, directories: list[Path]) -> dict:
    """The exported OCR JSON each crop came from, verified by SHA256 when present."""
    records = {}
    for info in manifest.get("documents", []):
        document = info["document"]
        expected = sorted({s["source_ocr_json_sha256"] for s in manifest["samples"] if s["document"] == document})
        name = f"{Path(document).stem}_vietocr_ocr_header_split.json"
        found = next((d / name for d in directories if (d / name).is_file()), None)
        if found is None:
            records[document] = {"status": "BLOCKED_MISSING", "required_file": name, "expected_sha256": expected}
        else:
            ok = len(expected) == 1 and sha256(found) == expected[0]
            records[document] = {"status": "PASS" if ok else "FAIL", "path": str(found), "expected_sha256": expected}
    statuses = {r["status"] for r in records.values()}
    return check("source_ocr_json", "BLOCKED" if "BLOCKED_MISSING" in statuses else
                 "FAIL" if "FAIL" in statuses else "PASS", {
                     "documents": records, "searched": [str(d) for d in directories],
                     "note": "Without the export, line_index/polygon/OCR provenance rests on the pack manifest; "
                             "an end-to-end rerun can reproduce the content but never the original file hash."})


def audit_cases_check(path: Path | None, manifest: dict) -> dict:
    ids = {s["id"] for s in manifest.get("samples", [])}
    if path and path.is_file():
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        unknown = [r for r in rows if r.get("id") and r["id"] not in ids]
        return check("audit_cases_csv", "FAIL" if unknown else "PASS", {"rows": len(rows), "unknown_ids": unknown})
    return check("audit_cases_csv", "BLOCKED", {
        "required_file": "vietdoc_5pdf_audit_cases.csv", "searched": str(path) if path else None,
        "diagnostic_targeted_ids_in_manifest": [s["id"] for s in manifest.get("samples", [])
                                                if s["sample_group"] == "diagnostic_targeted"],
        "note": "Selection reasons of the diagnostic samples are not recorded in the manifest."})


def text_layer_check(rows: list[dict], evidence: dict, recheck: Recheck) -> tuple[dict, dict]:
    """Embedded PDF text: independent of the evaluated model, present only on some pages."""
    crosscheck = {}
    for r in rows:
        found = evidence.get(r["id"]) or {}
        if not found.get("text_layer"):
            continue
        layer = " ".join(found["text_layer"].split())
        entry = {"text_layer": layer, "page_fonts": found["page_fonts"], "page_text_chars": found["page_text_chars"],
                 "ocr_matches_text_layer": nfc(r["ocr_original"]) == layer}
        reference = review(r).get("reference")
        if isinstance(reference, str):
            entry["reference_matches_text_layer"] = nfc(reference) == layer
            entry["reference_vs_text_layer_char_distance"] = distance(nfc(reference), layer)
            if not entry["reference_matches_text_layer"]:
                recheck.add(r["id"], "text_layer_disagrees_with_label", "high",
                            "Nhãn khác lớp chữ nhúng của PDF. Xem ảnh crop và gõ lại đúng nguyên văn dòng.",
                            f"PDF text layer: {layer}")
        crosscheck[r["id"]] = entry
    disagreements = [i for i, e in crosscheck.items() if e.get("reference_matches_text_layer") is False]
    corrected = [i for i, e in crosscheck.items()
                 if e.get("reference_matches_text_layer") and not e["ocr_matches_text_layer"]]
    return check("pdf_text_layer_crosscheck", "WARN" if disagreements else "PASS", {
        "lines_with_text_layer": len(crosscheck), "label_disagreements": disagreements,
        "human_corrections_confirmed_by_text_layer": corrected,
        "note": "Embedded text exists only on born-digital pages and digital-signature boxes. "
                "It is evidence for a human re-check, never written into labels."}), crosscheck


def corpus_check(rows: list[dict], recheck: Recheck) -> dict:
    """Missed diacritic slips in text the reviewer accepted from the OCR."""
    counts, display, used = corpus_counts()
    index = skeleton_index(counts)
    flagged = {}
    for r in rows:
        reference = review(r).get("reference")
        if not isinstance(reference, str):
            continue
        accepted = [f for f in corpus_variant_flags(reference, counts, display, index)
                    if f["bigram"] in nfc(r["ocr_original"])]
        if accepted:
            flagged[r["id"]] = accepted
            recheck.add(r["id"], "accepted_bigram_rare_in_corpus", "medium",
                        "Cụm từ trong nhãn (giữ nguyên từ OCR) hiếm gặp trong corpus không-mù trong khi một biến thể "
                        "dấu khác rất phổ biến; phóng to ảnh, gõ lại nguyên văn: "
                        + "; ".join(f["bigram"] for f in accepted),
                        "; ".join(f"corpus '{f['bigram']}'x{f['corpus_count']} vs "
                                  f"'{f['common_variant']}'x{f['variant_count']}" for f in accepted))
    return check("corpus_diacritic_variant_screen", "WARN" if flagged else "PASS", {
        "corpus_files": used, "min_variant_count": CORPUS_MIN_VARIANT, "ratio": CORPUS_RATIO, "flagged": flagged,
        "note": "Flags bigrams accepted from OCR that are rare in non-blind transcripts while a diacritic "
                "variant is >= ratio x commoner. Screening only (false positives expected); no text is replaced."})


def leakage_check(manifest: dict, rows: list[dict]) -> dict:
    """PDF hashes in repository datasets or earlier review packs; verbatim lines in training text."""
    searched = [REPO_ROOT / "datasets/vietnamese_recognition/real_documents.tsv",
                REPO_ROOT / "datasets/vietnamese_recognition/bakeoff_regression/source_documents.tsv",
                *sorted((REPO_ROOT / "demo/local_pdf_ocr/quality_work").glob("*/manifest.jsonl"))]
    texts = {p: p.read_text(encoding="utf-8") for p in searched if p.is_file()}
    found = {d["document"]: [str(p.relative_to(REPO_ROOT)) for p, t in texts.items() if d.get("pdf_sha256") in t]
             for d in manifest.get("documents", [])}
    seen = Counter()
    for path in CORPUS[:4]:  # training and validation transcripts
        if path.is_file():
            with path.open(encoding="utf-8", newline="") as stream:
                seen.update(nfc(row.get("text", "")) for row in csv.DictReader(stream, delimiter="\t"))
    verbatim = {r["id"]: seen[nfc(review(r)["reference"])] for r in rows
                if isinstance(review(r).get("reference"), str) and seen.get(nfc(review(r)["reference"]))}
    return check("leakage_and_independence", "FAIL" if any(found.values()) else "PASS", {
        "pdf_sha256_found_in": found, "reference_lines_seen_in_training_transcripts": verbatim,
        "searched": [str(p.relative_to(REPO_ROOT)) for p in texts],
        "note": "Identical boilerplate lines (recipient lists, national motto) recurring in training transcripts "
                "are expected and are not document leakage. The 10 diagnostic lines were chosen by looking at "
                "OCR output, so this pack is a diagnostic/dev set, not a blind test."})


def audit(pack_dir: Path, labels_path: Path, pdf_dir: Path | None, *, ocr_json_dirs=(),
          audit_cases: Path | None = None, requested: dict[str, str] | None = None,
          with_environment: bool = True) -> dict:
    """Integrity checks, recheck items and the trusted/quarantined split."""
    manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    html_path = pack_dir / "mo_review_40.html"
    pack = parse_html_pack(html_path) if html_path.is_file() else None
    samples, rows = manifest.get("samples", []), labels.get("labels", [])
    by_id, label_by_id = {s["id"]: s for s in samples}, {r["id"]: r for r in rows}
    recheck = Recheck()

    checks = [*contract_checks(labels, manifest, pack), *id_checks(manifest, rows, pack),
              review_state_check(labels, rows), hygiene_check(rows, recheck)]
    found, crops = crop_checks(pack_dir, samples, pack)
    checks += [*found, group_check(manifest)]
    source, evidence = pdf_check(manifest, pdf_dir)
    directories = [*ocr_json_dirs, *(p for p in (pdf_dir, pack_dir) if p)]
    checks += [source, ocr_json_check(manifest, directories), audit_cases_check(audit_cases, manifest)]
    layer, crosscheck = text_layer_check(rows, evidence, recheck)
    checks += [layer, corpus_check(rows, recheck), leakage_check(manifest, rows)]

    for identifier, question in (requested or {}).items():
        if identifier not in by_id:
            raise ValueError(f"STOP: requested recheck id is not in the pack: {identifier}")
        recheck.add(identifier, "requested_by_task", "high", question)
    for r in rows:
        if review(r).get("status") != "verified":
            recheck.add(r["id"], "uncertain_label", "high",
                        "Ảnh được đánh dấu khó đọc. Xác định đây có phải dòng chữ thật không (hay dấu/vết/nhiễu); "
                        "chỉ gõ nhãn nếu đọc được chắc chắn, nếu không giữ uncertain hoặc phân loại stamp_artifact.")

    # Trusted = verified with no high-priority open item; screen-only hits stay visible.
    partition = {"trusted": [], "pending_recheck": [], "uncertain_excluded": []}
    for r in rows:
        if review(r).get("status") != "verified":
            partition["uncertain_excluded"].append(r["id"])
        elif recheck.quarantines(r["id"]):
            partition["pending_recheck"].append(r["id"])
        else:
            partition["trusted"].append(r["id"])
    screen_hits = [i for i in partition["trusted"] if recheck.items.get(i)]
    failed = [c["check"] for c in checks if c["status"] == "FAIL"]
    blocked = [c["check"] for c in checks if c["status"] == "BLOCKED"]
    report = {
        "schema": "vietdoc_review40_label_integrity_v1",
        "status": "FAIL" if failed else ("PASS_WITH_BLOCKED_ITEMS_AND_QUARANTINE"
                                         if blocked or partition["pending_recheck"] else "PASS"),
        "failed_checks": failed,
        "blocked_checks": blocked,
        "inputs": {
            "pack_dir": str(pack_dir), "manifest_sha256": sha256(pack_dir / "manifest.json"),
            "review_html_sha256": sha256(html_path) if html_path.is_file() else None,
            "labels": str(labels_path), "labels_sha256": sha256(labels_path),
            "pdf_dir": str(pdf_dir) if pdf_dir else None,
        },
        "checks": checks,
        "samples": [{
            "id": s["id"], "document": s["document"], "page": s["page"], "line_index": s["line_index"],
            "sample_group": s["sample_group"], "region": review(label_by_id.get(s["id"], {})).get("region"),
            "status": review(label_by_id.get(s["id"], {})).get("status"),
            "reference_equals_ocr": review(label_by_id.get(s["id"], {})).get("reference") == s["ocr_original"],
            "crop": crops.get(s["id"]), "text_layer": crosscheck.get(s["id"]),
        } for s in samples],
        "recheck_items": {i: v for i, v in sorted(recheck.items.items())},
        "partition": partition,
        "screen_flagged_but_trusted": screen_hits,
        "quarantine_rule": "verified labels with a high-priority item (task request, PDF text-layer disagreement) "
                           "are pending; uncertain labels are excluded; medium screen hits stay trusted but listed",
        "labels_modified": False,
    }
    if with_environment:
        report["git"] = git_state()
        report["model_artifacts"] = model_state()
    return report


def write_recheck_csv(path: Path, report: dict, labels: dict, manifest: dict, pack_dir: Path) -> int:
    by_id = {s["id"]: s for s in manifest["samples"]}
    label_by_id = {r["id"]: r for r in labels["labels"]}
    trusted = set(report["partition"]["trusted"])
    order = {"high": 0, "medium": 1, "low": 2}
    rows = []
    for identifier, found in report["recheck_items"].items():
        s, state = by_id[identifier], review(label_by_id[identifier])
        rows.append({
            "priority": min((f["priority"] for f in found), key=order.get),
            "id": identifier, "document": s["document"], "page": s["page"], "line_index": s["line_index"],
            "sample_group": s["sample_group"], "region": state.get("region"), "label_status": state.get("status"),
            "crop_path": str((pack_dir / s["image_file"]).resolve()),
            "ocr_original": s["ocr_original"], "current_reference": state.get("reference") or "",
            "issue_codes": ";".join(sorted({f["code"] for f in found})),
            "question_for_reviewer": " | ".join(dict.fromkeys(f["question"] for f in found)),
            "evidence": " | ".join(dict.fromkeys(f["evidence"] for f in found if f["evidence"])),
            "in_trusted_set": "yes" if identifier in trusted else "no",
            "reviewer_decision": "", "reviewer_transcription": "", "reviewer": "", "reviewed_at": "",
        })
    rows.sort(key=lambda r: (order[r["priority"]], r["document"], r["page"], r["line_index"]))
    with path.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ["id"])
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


# --------------------------------------------------------------- metrics

def raw_metrics(pairs: list[tuple[str, str]]) -> dict:
    """Like benchmark.metrics but without Unicode normalisation."""
    char_errors = sum(distance(r, h) for r, h in pairs)
    chars = sum(len(r) for r, _ in pairs)
    word_errors = sum(distance(r.split(), h.split()) for r, h in pairs)
    words = sum(len(r.split()) for r, _ in pairs)
    return {"char_errors": char_errors, "reference_chars": chars, "cer": char_errors / chars,
            "word_errors": word_errors, "reference_words": words, "wer": word_errors / words,
            "exact_lines": sum(r == h for r, h in pairs)}


def wilson(successes: int, total: int, z: float = 1.959964) -> list[float] | None:
    if not total:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [round(max(0.0, centre - half), 6), round(min(1.0, centre + half), 6)]


def bootstrap(records: list[dict], *, by_document: bool = False) -> dict | None:
    """Percentile 95% intervals of micro CER/WER by resampling lines (or whole PDFs)."""
    if not records:
        return None
    rng = random.Random(BOOTSTRAP_SEED)
    if by_document:
        grouped = defaultdict(list)
        for r in records:
            grouped[r["document"]].append(r)
        units = list(grouped.values())
    else:
        units = [[r] for r in records]
    cers, wers = [], []
    for _ in range(BOOTSTRAP_DRAWS):
        drawn = [line for _ in units for line in units[rng.randrange(len(units))]]
        chars = sum(r["reference_chars"] for r in drawn)
        words = sum(r["reference_words"] for r in drawn)
        cers.append(sum(r["char_errors"] for r in drawn) / chars)
        wers.append(sum(r["word_errors"] for r in drawn) / words)
    cers.sort()
    wers.sort()
    low, high = int(0.025 * BOOTSTRAP_DRAWS), int(0.975 * BOOTSTRAP_DRAWS) - 1
    return {"unit": "document" if by_document else "line", "units": len(units), "draws": BOOTSTRAP_DRAWS,
            "seed": BOOTSTRAP_SEED, "cer_95": [round(cers[low], 6), round(cers[high], 6)],
            "wer_95": [round(wers[low], 6), round(wers[high], 6)]}


def score(records: list[dict]) -> dict | None:
    if not records:
        return None
    pairs = [(r["reference"], r["hypothesis"]) for r in records]
    result = metrics(pairs)
    result["mismatch_lines"] = result["lines"] - result["exact_lines"]
    result["exact_line_rate_wilson_95"] = wilson(result["exact_lines"], result["lines"])
    raw = raw_metrics(pairs)
    result["raw_unnormalised_equals_nfc"] = all(raw[k] == result[k] for k in
                                               ("char_errors", "reference_chars", "word_errors", "reference_words",
                                                "exact_lines"))
    return result


def breakdown(records: list[dict], key) -> dict:
    grouped = defaultdict(list)
    for r in records:
        grouped[key(r)].append(r)
    return {name: score(rows) for name, rows in sorted(grouped.items())}


def error_summary(records: list[dict]) -> dict:
    spans = [s for r in records for s in r["error_spans"]]
    categories, category_cost, details = Counter(), Counter(), Counter()
    for s in spans:
        for c in s["categories"]:
            categories[c] += 1
            category_cost[c] += s["cost"]
        details.update(d for d in s["details"] if ":" in d)
    entities = {}
    for kind in ("doc_number", "agency_name", "email"):
        instances = [(r, e) for r in records for e in r["entities"] if e["type"] == kind]
        wrong = [(r, e) for r, e in instances if any(overlaps(s, e) for s in r["error_spans"])]
        entities[kind] = {
            "lines_with_entity": len({r["id"] for r, _ in instances}),
            "instances": len(instances),
            "instances_with_error": len(wrong),
            "instance_exact_rate": round(1 - len(wrong) / len(instances), 6) if instances else None,
            "errors": [{"id": r["id"], "entity": e["text"],
                        "error_spans": [f"{s['reference']}→{s['hypothesis']}" for s in r["error_spans"] if overlaps(s, e)]}
                       for r, e in wrong],
        }
    tracked = [{"id": r["id"], "span": f"{s['reference']}→{s['hypothesis']}"} for r in records
               for s in r["error_spans"] if "tone_changed:hoi->sac" in s["details"]]
    return {
        "error_spans": len(spans),
        "char_errors": sum(s["cost"] for s in spans),
        "spans_by_category": dict(categories.most_common()),
        "char_errors_by_category": dict(category_cost.most_common()),
        "diacritic_details": dict(details.most_common()),
        "entities": entities,
        "tracked_hoi_to_sac_like_chuan_chuan": tracked,
        "note": "Categories describe visible edits (reference→OCR); a span may carry several. "
                "They are not root causes.",
    }


def line_records(labels: dict, manifest: dict, partition: dict, agencies: list[str],
                 predictions: dict[str, str] | None = None) -> list[dict]:
    """One record per verified label; ``predictions`` replaces the stored OCR text."""
    by_id = {s["id"]: s for s in manifest["samples"]}
    where = {i: name for name, ids in partition.items() for i in ids}
    records = []
    for row in labels["labels"]:
        review = row["review"]
        if review.get("status") != "verified":
            continue
        reference = review["reference"]
        hypothesis = row["ocr_original"] if predictions is None else predictions[row["id"]]
        ref, hyp = nfc(reference), nfc(hypothesis)
        records.append({
            "id": row["id"], "document": row["document"], "page": row["page"], "line_index": row["line_index"],
            "sample_group": row["sample_group"], "region": review.get("region"),
            "polygon": by_id[row["id"]]["polygon"], "partition": where.get(row["id"]),
            "reference": reference, "hypothesis": hypothesis, "exact": ref == hyp,
            "char_errors": distance(ref, hyp), "reference_chars": len(ref),
            "word_errors": distance(ref.split(), hyp.split()), "reference_words": len(ref.split()),
            "difference_tags": difference_tags(reference, hypothesis),
            "error_spans": error_spans(reference, hypothesis),
            "entities": entity_spans(reference, agencies),
        })
    return records


def evaluate_set(records: list[dict]) -> dict | None:
    if not records:
        return None
    short = lambda r: r["document"].split("_")[0].split(".")[0]  # noqa: E731
    return {
        "overall": score(records),
        "by_pdf": breakdown(records, lambda r: r["document"]),
        "by_page": breakdown(records, lambda r: f"{short(r)} p{r['page']}"),
        "by_sample_group": breakdown(records, lambda r: r["sample_group"]),
        "by_region": breakdown(records, lambda r: r["region"]),
        "by_group_and_region": breakdown(records, lambda r: f"{r['sample_group']} / {r['region']}"),
        "uncertainty": {"line_bootstrap": bootstrap(records), "document_bootstrap": bootstrap(records, by_document=True)},
        "error_analysis": error_summary(records),
    }


def baseline_metrics(labels: dict, manifest: dict, report: dict) -> dict:
    agencies = agency_names()
    partition = report["partition"]
    records = line_records(labels, manifest, partition, agencies)
    verified = records
    trusted = [r for r in records if r["partition"] == "trusted"]
    screened = set(report.get("screen_flagged_but_trusted", []))
    strict = [r for r in trusted if r["id"] not in screened]
    pending = [r for r in records if r["partition"] == "pending_recheck"]
    as_labeled = score(verified)
    observed = {"verified": len(verified), "uncertain": len(partition["uncertain_excluded"]),
                "exact": as_labeled["exact_lines"], "mismatch": as_labeled["mismatch_lines"],
                "cer": round(as_labeled["cer"], 6), "wer": round(as_labeled["wer"], 6)}
    matches = (all(observed[k] == PRELIMINARY[k] for k in ("verified", "uncertain", "exact", "mismatch"))
               and abs(as_labeled["cer"] - PRELIMINARY["cer"]) < 5e-5
               and abs(as_labeled["wer"] - PRELIMINARY["wer"]) < 5e-5)
    lower_bound = None
    if pending:
        extra = len(pending)
        lower_bound = {
            "assumption": "every pending label is wrong, i.e. the reviewer accepted an OCR error; "
                          "each such line then has >=1 more character and word error (minimum, not a guess of the text)",
            "lines": len(verified),
            "exact_lines_at_most": as_labeled["exact_lines"] - sum(r["exact"] for r in pending),
            "cer_at_least": round((as_labeled["char_errors"] + extra) / as_labeled["reference_chars"], 6),
            "wer_at_least": round((as_labeled["word_errors"] + extra) / as_labeled["reference_words"], 6),
        }
    layer = {s["id"]: s["text_layer"]["text_layer"] for s in report["samples"] if s.get("text_layer")}
    independent = [(layer[r["id"]], r["hypothesis"]) for r in records if r["id"] in layer]
    return {
        "schema": "vietdoc_review40_baseline_metrics_v1",
        "status": "DIAGNOSTIC_DEV_SET_METRICS_NOT_SYSTEM_QUALITY",
        "baseline": {
            "source": "ocr_original strings in the labels/manifest (unchanged exported OCR, never re-run here)",
            "engine": "PaddleOCR PP-OCRv6_medium_det + frozen VietOCR B ONNX (phase4_exp_b_width1024), "
                      "header split on, CPUExecutionProvider",
        },
        "normalization": {
            "applied": "Unicode NFC on reference and OCR before scoring (benchmark.metrics)",
            "not_applied": ["case folding", "whitespace collapsing", "punctuation removal",
                            "diacritic stripping", "dictionary or spelling correction"],
            "cer": "sum(char Levenshtein distance) / sum(reference chars) — micro average",
            "wer": "sum(token Levenshtein distance over whitespace split) / sum(reference tokens) — micro average",
            "exact_match": "NFC reference == NFC OCR for the whole line",
        },
        "reconciliation_with_preliminary": {
            "preliminary": PRELIMINARY, "observed_as_labeled": observed, "matches": matches,
            "explanation": "Same 39 verified lines, uncertain line excluded, NFC only, micro-averaged. "
                           "Raw (unnormalised) scores are identical because every string is already NFC.",
        },
        "sets": {
            "as_labeled_verified": {
                "definition": "all 39 human-verified labels exactly as downloaded (includes pending recheck lines)",
                "ids": [r["id"] for r in verified], **evaluate_set(verified),
            },
            "trusted": {
                "definition": "verified labels without a high-priority recheck item (official figure of this report)",
                "ids": [r["id"] for r in trusted], **(evaluate_set(trusted) or {}),
            },
            "trusted_without_screen_hits": {
                "definition": "trusted minus lines carrying a medium screen hit; robustness check only",
                "ids": [r["id"] for r in strict], "overall": score(strict),
            },
            "pending_recheck_as_labeled": {
                "definition": "verified labels awaiting human re-check; scored only for transparency",
                "ids": [r["id"] for r in pending], "overall": score(pending),
            },
        },
        "excluded_uncertain": partition["uncertain_excluded"],
        "sensitivity_if_pending_labels_are_wrong": lower_bound,
        "independent_text_layer_check": {
            "definition": "OCR vs embedded PDF text on lines whose page carries it (born-digital pages, "
                          "signature boxes); a second, model-independent reference, not the label set",
            "lines": len(independent),
            "metrics": metrics(independent) if independent else None,
        },
        "per_line": [{k: v for k, v in r.items() if k != "polygon"} for r in records],
        "caveats": [
            "40 lines = 30 hash-selected longer lines + 10 diagnostic lines picked because the OCR looked wrong; "
            "neither group, nor the pool, estimates whole-document or whole-system CER.",
            "The diagnostic group is error-enriched by construction; never average it with the representative group "
            "to claim accuracy.",
            "Line-level bootstrap ignores that lines share a PDF; the 5-PDF bootstrap shows how wide the "
            "uncertainty really is.",
            "This pack was built after looking at OCR output; treat it as a diagnostic/dev set, not a blind test.",
        ],
    }


# ---------------------------------------------------------- candidate

def load_predictions(path: Path) -> dict[str, str]:
    predictions = {}
    for row in read_jsonl(path):
        identifier, text = row.get("id"), row.get("prediction")
        if not isinstance(identifier, str) or not isinstance(text, str) or identifier in predictions:
            raise ValueError("STOP: candidate rows need a unique id and a prediction string")
        predictions[identifier] = text
    return predictions


def probe_predictions(path: Path) -> dict[str, str]:
    """Frozen-model predictions on the context-padded pack crops, from a parity report."""
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("schema") != "vietdoc_review40_baseline_parity_v1":
        raise ValueError("STOP: not a vietdoc_review40 parity report")
    return {r["id"]: r["pack_crop_prediction"] for r in report["results"]}


def word_correct(reference: str, hypothesis: str, entries: list[str]) -> dict[str, bool]:
    """For each hard-case word/phrase in the reference: reproduced exactly at its aligned place?"""
    ref_words, hyp_words = nfc(reference).split(), nfc(hypothesis).split()
    ops = alignment([w.lower() for w in ref_words], [w.lower() for w in hyp_words])
    correct = {i: op == "equal" for op, i, _ in ops if op != "insert"}
    clean = [re.sub(r"^\W+|\W+$", "", w.lower()) for w in ref_words]
    found = {}
    for entry in entries:
        size = len(entry.split())
        for start in range(len(clean) - size + 1):
            if " ".join(clean[start:start + size]) == entry:
                found[f"{entry}@{start}"] = all(correct.get(k, False) for k in range(start, start + size))
    return found


def compare_candidate(labels: dict, manifest: dict, report: dict, predictions: dict[str, str], name: str,
                      *, kind: str = "CANDIDATE") -> dict:
    partition = report["partition"]
    scored = set(partition["trusted"]) | set(partition["pending_recheck"])
    missing = sorted(scored - set(predictions))
    unknown = sorted(set(predictions) - {s["id"] for s in manifest["samples"]})
    if missing or unknown:
        raise ValueError(f"STOP: candidate predictions missing {missing[:5]} or unknown {unknown[:5]}")
    agencies = agency_names()
    entries = hard_case_entries()
    baseline = {r["id"]: r for r in line_records(labels, manifest, partition, agencies)}
    candidate = {r["id"]: r for r in line_records(labels, manifest, partition, agencies, predictions)}
    lines, regressions, tracked, hard_regressions = [], [], [], []
    for identifier, base in baseline.items():
        cand = candidate[identifier]
        status = ("regressed" if cand["char_errors"] > base["char_errors"] else
                  "improved" if cand["char_errors"] < base["char_errors"] else
                  "unchanged" if nfc(cand["hypothesis"]) == nfc(base["hypothesis"]) else "changed_same_cost")
        old = {(s["ref_start"], s["ref_end"], s["hypothesis"]) for s in base["error_spans"]}
        new_spans = [s for s in cand["error_spans"] if (s["ref_start"], s["ref_end"], s["hypothesis"]) not in old]
        base_words = word_correct(base["reference"], base["hypothesis"], entries)
        cand_words = word_correct(cand["reference"], cand["hypothesis"], entries)
        lost = sorted(k for k, ok in base_words.items() if ok and not cand_words.get(k, False))
        line = {
            "id": identifier, "partition": base["partition"], "sample_group": base["sample_group"],
            "region": base["region"], "reference": base["reference"],
            "baseline": base["hypothesis"], "candidate": cand["hypothesis"], "status": status,
            "baseline_char_errors": base["char_errors"], "candidate_char_errors": cand["char_errors"],
            "baseline_word_errors": base["word_errors"], "candidate_word_errors": cand["word_errors"],
            "baseline_to_candidate_edits": edits(base["hypothesis"], cand["hypothesis"]),
            "new_error_spans": new_spans, "hard_case_words_lost": lost,
        }
        lines.append(line)
        if status == "regressed" or cand["word_errors"] > base["word_errors"]:
            regressions.append(identifier)
        tracked += [{"id": identifier, "span": f"{s['reference']}→{s['hypothesis']}"}
                    for s in new_spans if any(d.startswith("tone_changed:hoi->sac") for d in s["details"])]
        if lost:
            hard_regressions.append({"id": identifier, "lost": lost})

    def pair(ids):
        b = score([baseline[i] for i in ids if i in baseline])
        c = score([candidate[i] for i in ids if i in candidate])
        return {"baseline": b, "candidate": c} if b else None

    trusted = pair(partition["trusted"])
    eligible = bool(trusted and trusted["candidate"]["char_errors"] < trusted["baseline"]["char_errors"]
                    and trusted["candidate"]["word_errors"] <= trusted["baseline"]["word_errors"]
                    and not regressions and not tracked and not hard_regressions)
    return {
        "schema": "vietdoc_review40_candidate_comparison_v1",
        "kind": kind,
        "candidate": name,
        "decision": "ELIGIBLE_FOR_LARGER_REGRESSION_TRIAL_ONLY" if eligible else "NO_GO",
        "decision_rule": "fewer char errors and no more word errors on the trusted set, zero per-line "
                         "regressions on all verified lines, zero new hỏi→sắc tone swaps, zero hard-case words lost",
        "not_blind": True,
        "trusted": trusted,
        "as_labeled_verified": pair(sorted(scored)),
        "line_regressions": regressions,
        "new_hoi_to_sac_spans": tracked,
        "hard_case_word_regressions": hard_regressions,
        "lines": lines,
        "baseline_outputs_modified": False,
    }


# ---------------------------------------------------------------- parity

def parity(pack_dir: Path, pdf_dir: Path, output: Path, *, export_crops: Path | None = None) -> dict:
    """Frozen ONNX on the pack crops and on crops re-derived from PDF + polygon.

    The re-derived crop is what the local website feeds the recognizer; with
    ``export_crops`` it is saved so a candidate can be run on the same input.
    """
    if output.exists() or (export_crops and export_crops.exists()):
        raise ValueError(f"STOP: report or crop directory already exists: {output} {export_crops or ''}")
    import cv2
    import fitz
    import numpy as np
    from paddlex.inference.pipelines.components import CropByPolys
    from PIL import Image

    from demo.local_pdf_ocr.backend.contract import verify_frozen_onnx
    from demo.local_pdf_ocr.backend.engine import OnnxVietocrB

    manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    metadata = verify_frozen_onnx(require_weights=True)
    recognizer = OnnxVietocrB(metadata)
    cropper = CropByPolys(det_box_type="quad")
    if export_crops:
        export_crops.mkdir(parents=True)
    pages, results = {}, []
    for s in manifest["samples"]:
        pdf_path = pdf_dir / s["document"]
        if sha256(pdf_path) != s["pdf_sha256"]:
            raise ValueError(f"STOP: PDF hash differs: {pdf_path}")
        key = (s["document"], s["page"])
        if key not in pages:
            with fitz.open(pdf_path) as pdf:
                page = pdf[s["page"] - 1]
                zoom = page_zoom(page.rect.width, page.rect.height)
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csRGB, alpha=False)
                rgb = np.asarray(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
                pages[key] = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        crop_path = pack_dir / s["image_file"]
        if sha256(crop_path) != s["image_sha256"]:
            raise ValueError(f"STOP: crop hash differs: {crop_path}")
        with Image.open(crop_path) as source:
            pack_rgb = np.asarray(source.convert("RGB"))
        derived_bgr = cropper(pages[key], [np.asarray(s["polygon"], dtype=np.float32).tolist()])[0]
        derived_rgb = cv2.cvtColor(derived_bgr, cv2.COLOR_BGR2RGB)
        identical = pack_rgb.shape == derived_rgb.shape and bool(np.array_equal(pack_rgb, derived_rgb))
        derived_text, derived_limit = recognizer.predict(Image.fromarray(derived_rgb))
        pack_text, pack_limit = recognizer.predict(Image.fromarray(pack_rgb))
        record = {
            "id": s["id"],
            "rederived_shape_hw": list(derived_rgb.shape[:2]), "pack_shape_hw": list(pack_rgb.shape[:2]),
            "pack_margin_hw": [pack_rgb.shape[0] - derived_rgb.shape[0], pack_rgb.shape[1] - derived_rgb.shape[1]],
            "crop_pixels_identical_to_rederived": identical,
            "rederived_crop_prediction": derived_text,
            "rederived_reproduces_ocr_original": derived_text == s["ocr_original"] and not derived_limit,
            "pack_crop_prediction": pack_text,
            "pack_crop_reproduces_ocr_original": pack_text == s["ocr_original"] and not pack_limit,
        }
        if export_crops:
            target = export_crops / f"{s['id']}.png"
            Image.fromarray(derived_rgb).save(target)
            record["exported_crop_sha256"] = sha256(target)
        results.append(record)
    margins = [r["pack_margin_hw"] for r in results]
    report = {
        "schema": "vietdoc_review40_baseline_parity_v1",
        "status": "EVIDENCE_ONLY_NOT_A_BASELINE",
        "frozen_checkpoint_sha256": metadata["checkpoint_sha256"],
        "inference_provider": "CPUExecutionProvider",
        "samples": len(results),
        "rederived_crop_reproduces_ocr_original": sum(r["rederived_reproduces_ocr_original"] for r in results),
        "rederived_not_reproduced_ids": [r["id"] for r in results if not r["rederived_reproduces_ocr_original"]],
        "pack_crops_identical_to_rederived": sum(r["crop_pixels_identical_to_rederived"] for r in results),
        "pack_crop_reproduces_ocr_original": sum(r["pack_crop_reproduces_ocr_original"] for r in results),
        "pack_margin_px": {"height_min_max": [min(m[0] for m in margins), max(m[0] for m in margins)],
                           "width_min_max": [min(m[1] for m in margins), max(m[1] for m in margins)]},
        "interpretation": "The re-derived crop (PDF raster + polygon + CropByPolys) is the recognizer input. "
                          "Pack crops are context-padded review images; predictions on them are a diagnostic "
                          "probe, never the baseline.",
        "exported_crops_dir": str(export_crops) if export_crops else None,
        "results": results,
        "labels_used": False,
        "blind_test_used": False,
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


# ------------------------------------------------------------------ CLI

def parse_recheck(values: list[str]) -> dict[str, str]:
    """``ID`` or ``ID=question`` pairs from the command line."""
    requested = {}
    for value in values:
        identifier, _, question = value.partition("=")
        requested[identifier.strip()] = question.strip() or "Yêu cầu xác minh lại từ đề bài; xem ảnh và gõ lại nguyên văn."
    return requested


def evaluate(args) -> dict:
    output = args.output_dir
    comparisons = []
    if args.candidate:
        comparisons.append(("candidate_comparison.json", args.candidate, "CANDIDATE",
                            args.candidate_name or args.candidate.stem))
    if args.parity_probe:
        comparisons.append(("probe_context_padded_crops_comparison.json", args.parity_probe,
                            "DIAGNOSTIC_PROBE_NOT_A_DEPLOYMENT_CANDIDATE",
                            "frozen_b1024_onnx_on_context_padded_review_crops"))
    targets = [output / name for name in (*OUTPUTS, *(c[0] for c in comparisons))]
    existing = [str(t) for t in targets if t.exists()]
    if existing:
        raise ValueError(f"STOP: will not overwrite existing reports: {existing}")
    labels_before = sha256(args.labels)
    report = audit(args.pack_dir, args.labels, args.pdf_dir, ocr_json_dirs=tuple(args.ocr_json_dir),
                   audit_cases=args.audit_cases, requested=parse_recheck(args.recheck))
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    manifest = json.loads((args.pack_dir / "manifest.json").read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=True)
    result = baseline_metrics(labels, manifest, report)
    compared = {}
    for name, source, kind, label in comparisons:
        predictions = probe_predictions(source) if kind.startswith("DIAGNOSTIC") else load_predictions(source)
        compared[name] = {**compare_candidate(labels, manifest, report, predictions, label, kind=kind),
                          "predictions_source": str(source), "predictions_source_sha256": sha256(source)}
    if sha256(args.labels) != labels_before:
        raise RuntimeError("STOP: labels changed during evaluation")
    with (output / "label_integrity_report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    count = write_recheck_csv(output / "manual_recheck_required.csv", report, labels, manifest, args.pack_dir)
    with (output / "baseline_metrics.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    for name, comparison in compared.items():
        with (output / name).open("x", encoding="utf-8") as stream:
            json.dump(comparison, stream, ensure_ascii=False, indent=2)
    trusted = result["sets"]["trusted"].get("overall") or {}
    return {
        "integrity_status": report["status"], "failed_checks": report["failed_checks"],
        "blocked_checks": report["blocked_checks"], "recheck_rows": count,
        "partition": {k: len(v) for k, v in report["partition"].items()},
        "screen_flagged_but_trusted": len(report["screen_flagged_but_trusted"]),
        "as_labeled": result["reconciliation_with_preliminary"]["observed_as_labeled"],
        "reconciles_with_preliminary": result["reconciliation_with_preliminary"]["matches"],
        "trusted": {k: trusted.get(k) for k in ("lines", "exact_lines", "cer", "wer")},
        "comparisons": {name: c["decision"] for name, c in compared.items()} or "NO_CANDIDATE_SUPPLIED",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("evaluate", help="model-free integrity, recheck list and metrics")
    run.add_argument("--pack-dir", type=Path, required=True)
    run.add_argument("--labels", type=Path, required=True)
    run.add_argument("--pdf-dir", type=Path)
    run.add_argument("--ocr-json-dir", type=Path, action="append", default=[])
    run.add_argument("--audit-cases", type=Path)
    run.add_argument("--recheck", action="append", default=[], metavar="ID[=QUESTION]")
    run.add_argument("--candidate", type=Path, help="JSONL with {id, prediction} per pack line")
    run.add_argument("--candidate-name")
    run.add_argument("--parity-probe", type=Path,
                     help="parity report; compares frozen-model output on the padded review crops (diagnostic only)")
    run.add_argument("--output-dir", type=Path, required=True)
    check_parity = commands.add_parser("parity", help="frozen ONNX + crop re-derivation evidence")
    check_parity.add_argument("--pack-dir", type=Path, required=True)
    check_parity.add_argument("--pdf-dir", type=Path, required=True)
    check_parity.add_argument("--output", type=Path, required=True)
    check_parity.add_argument("--export-crops", type=Path, help="new directory for the recognizer-input crops")
    args = parser.parse_args(argv)
    if args.command == "evaluate":
        print(json.dumps(evaluate(args), ensure_ascii=False, indent=2))
    else:
        report = parity(args.pack_dir, args.pdf_dir, args.output, export_crops=args.export_crops)
        print(json.dumps({k: report[k] for k in (
            "samples", "rederived_crop_reproduces_ocr_original", "rederived_not_reproduced_ids",
            "pack_crops_identical_to_rederived", "pack_crop_reproduces_ocr_original", "pack_margin_px")},
            ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Paired evaluation of the crop-geometry runs against the frozen baseline (arm A0).

Run from repo root:
  .venv-demo\\Scripts\\python.exe -m experiments.crop_geometry.evaluate --work-dir <dir>

Reads the runs in <dir>/runs, the sources manifest and the pre-registration, and
writes crop_candidate_metrics.json, crop_experiment_matrix.csv and
paired_lines.jsonl into <dir> (never over existing files). References come from
humans (40-line pack trusted labels, review_01, review_numbers_02) or from the
PDF text layer, never from a model. Config selection follows the
pre-registered rule on the DEV set only.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from demo.local_pdf_ocr.quality.benchmark import distance, metrics, nfc
from demo.local_pdf_ocr.quality.vietdoc_review40 import (
    agency_names, alignment, entity_spans, error_spans, hard_case_entries, recognizer_vocabulary, word_correct,
)

REPO = Path(__file__).resolve().parents[2]
CANARIES = ("chuẩn", "triển", "đảng")
ZERO_O_Q, ONE_I_U = frozenset("0OoQq"), frozenset("1IlUu|")
DATE_PATTERNS = (r"ngày\s+\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+\d{4}", r"tháng\s+\d{1,2}\s+năm\s+\d{4}",
                 r"\b\d{1,2}[./-]\d{1,2}[./-]\d{4}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?", r"năm\s+\d{4}")
BORN_DIGITAL = ("10300_", "1953_", "10314_", "76-bxd", "10333_", "137-vbhn")


# ------------------------------------------------------------- references

def human_references(v1_dir: Path, labels_v1: Path, quality_work: Path) -> dict[str, dict[str, str]]:
    """Keys document|page|line -> reference, per human-labelled regression set."""
    partition = json.loads((v1_dir / "label_integrity_report.json").read_text(encoding="utf-8"))["partition"]
    trusted = set(partition["trusted"])
    h40 = {f"{r['document']}|{r['page']}|{r['line_index']}": r["review"]["reference"]
           for r in json.loads(labels_v1.read_text(encoding="utf-8"))["labels"] if r["id"] in trusted}
    sets = {"REG-H40": h40}
    for name, folder in (("REG-H72", "review_01"), ("REG-H5", "review_numbers_02")):
        manifest = {json.loads(l)["id"]: json.loads(l) for l in (quality_work / folder / "manifest.jsonl").read_text(encoding="utf-8").splitlines()}
        labels = [json.loads(l) for l in (quality_work / folder / "labels.jsonl").read_text(encoding="utf-8").splitlines()]
        sets[name] = {f"{manifest[l['id']]['document']}|{manifest[l['id']]['page']}|{manifest[l['id']]['line_index']}": l["reference"]
                      for l in labels if l.get("verified") is True and isinstance(l.get("reference"), str)}
    return sets


def overlap_fraction(word: tuple, box: tuple) -> float:
    x0, y0, x1, y1 = word[:4]
    inter = max(0.0, min(x1, box[2]) - max(x0, box[0])) * max(0.0, min(y1, box[3]) - max(y0, box[1]))
    area = max(1e-9, (x1 - x0) * (y1 - y0))
    return inter / area


def text_layer_reference(words: list, polygon: list, zoom: float, vocabulary: set[str] | None) -> tuple[str | None, str]:
    """Reference from embedded PDF words inside a polygon, or (None, why not). Geometry only."""
    xs, ys = [p[0] / zoom for p in polygon], [p[1] / zoom for p in polygon]
    box = (min(xs), min(ys), max(xs), max(ys))
    inside, ambiguous = [], False
    for word in words:
        cx, cy = (word[0] + word[2]) / 2, (word[1] + word[3]) / 2
        share = overlap_fraction(word, box)
        if box[0] <= cx <= box[2] and box[1] <= cy <= box[3]:
            if share < 0.5:
                return None, "word_straddles_polygon"
            inside.append(word)
        elif share >= 0.3:
            ambiguous = True
    if ambiguous:
        return None, "ambiguous_word_assignment"
    if not inside:
        return None, "no_text_layer_words"
    # One visual line per polygon: read left to right (a number typed into a blank is often a
    # separate text object), and put a space only where the words are visibly apart.
    inside.sort(key=lambda w: (w[0], w[1]))
    parts = [inside[0][4]]
    for previous, current in zip(inside, inside[1:]):
        parts.append((" " if current[0] - previous[2] > 0.5 else "") + current[4])
    text = nfc("".join(parts))
    if vocabulary is not None and any(c not in vocabulary for c in text):
        return None, "out_of_vocab_reference"
    return text, "ok"


def text_layer_sets(sources: list[dict]) -> tuple[dict[str, dict[str, str]], dict]:
    import fitz

    vocabulary = recognizer_vocabulary()
    sets, reasons = {"DEV": {}, "REG-TL": {}}, Counter()
    for source in sources:
        target = "DEV" if source["set"] == "dev2_born_digital" else "REG-TL"
        export = json.loads(Path(source["ocr_json"]).read_text(encoding="utf-8"))
        with fitz.open(source["pdf"]) as pdf:
            for page in export["pages"]:
                fpage = pdf[page["page"] - 1]
                zoom = min(2.0, math.sqrt(12_000_000 / (fpage.rect.width * fpage.rect.height)))
                words = fpage.get_text("words", sort=False)
                for line in page["lines"]:
                    reference, why = text_layer_reference(words, line["polygon"], zoom, vocabulary)
                    reasons[f"{target}:{why}"] += 1
                    if reference is not None:
                        sets[target][f"{source['document']}|{page['page']}|{line['line_index']}"] = reference
    return sets, dict(reasons)


# --------------------------------------------------------------- measures

def date_spans(text: str) -> list[dict]:
    spans = []
    for pattern in DATE_PATTERNS:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            if not any(match.start() < s["end"] and match.end() > s["start"] for s in spans):
                spans.append({"type": "date", "start": match.start(), "end": match.end(), "text": match.group()})
    return spans


def substitution_pairs(reference: str, hypothesis: str) -> list[tuple[str, str]]:
    ref, hyp = nfc(reference), nfc(hypothesis)
    return [(ref[i], hyp[j]) for op, i, j in alignment(ref, hyp) if op == "substitute"]


def line_measures(reference: str, hypothesis: str, agencies: list[str], entries: list[str]) -> dict:
    ref, hyp = nfc(reference), nfc(hypothesis)
    spans = error_spans(ref, hyp)
    entities = entity_spans(ref, agencies) + date_spans(ref)
    wrong = Counter()
    for entity in entities:
        start, end = entity["start"], entity["end"]
        if any((s["ref_start"] < end and s["ref_end"] > start) or (s["ref_start"] == s["ref_end"] and start <= s["ref_start"] <= end)
               for s in spans):
            wrong[entity["type"]] += 1
    pairs = substitution_pairs(ref, hyp)
    words = word_correct(ref, hyp, entries)
    return {
        "char_errors": distance(ref, hyp), "chars": len(ref),
        "word_errors": distance(ref.split(), hyp.split()), "words": len(ref.split()), "exact": ref == hyp,
        "tone": Counter(d for s in spans for d in s["details"] if d.startswith(("tone_", "modifier_"))),
        "zero_O_Q": sum(a != b and a in ZERO_O_Q and b in ZERO_O_Q for a, b in pairs),
        "one_I_U": sum(a != b and a in ONE_I_U and b in ONE_I_U for a, b in pairs),
        "entities": Counter(e["type"] for e in entities), "entities_wrong": wrong,
        "hard_case_correct": words,
        "canary_correct": {k: v for k, v in words.items() if k.split("@")[0] in CANARIES},
    }


def sign_test(improved: int, regressed: int) -> dict:
    n = improved + regressed
    if n == 0:
        return {"n": 0, "p_one_sided_improvement": 1.0, "p_two_sided": 1.0}
    tail = lambda k: sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n  # noqa: E731
    upper, lower = tail(improved), 1 - tail(improved + 1)
    return {"n": n, "p_one_sided_improvement": round(upper, 6), "p_two_sided": round(min(1.0, 2 * min(upper, lower)), 6)}


def document_group(document: str) -> str:
    return "born_digital" if document.startswith(BORN_DIGITAL) else "scanned"


# --------------------------------------------------------------- evaluate

def load_runs(runs_dir: Path) -> tuple[dict[str, dict[str, dict]], list[dict]]:
    """key -> config -> record, plus each run manifest."""
    by_key, manifests = defaultdict(dict), []
    for run in sorted(p for p in runs_dir.iterdir() if p.is_dir()):
        manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
        if manifest["parity_mismatches"] or manifest.get("reference_text_used"):
            raise ValueError(f"STOP: run {run.name} failed A0 parity or used reference text")
        manifests.append({"run": run.name, **{k: manifest[k] for k in ("model", "code_sha256", "configs", "predictions_run")},
                          "documents": [s["document"] for s in manifest["sources"]]})
        for line in (run / "results.jsonl").read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record["config"] in by_key[record["key"]]:
                raise ValueError(f"STOP: duplicate result {record['key']} {record['config']}")
            by_key[record["key"]][record["config"]] = record
    return by_key, manifests


def evaluate_set(name: str, references: dict[str, str], by_key: dict, configs: list[str], agencies, entries) -> tuple[dict, list[dict]]:
    keys = sorted(k for k in references if k in by_key)
    missing = sorted(k for k in references if k not in by_key)
    base = {k: line_measures(references[k], by_key[k]["A0"]["text"], agencies, entries) for k in keys}
    summary, pairs = {"lines": len(keys), "references_without_run": len(missing)}, []
    for config in configs:
        rows = [(references[k], by_key[k][config]["text"]) for k in keys]
        measures = {k: (base[k] if config == "A0" else line_measures(references[k], by_key[k][config]["text"], agencies, entries)) for k in keys}
        improved = [k for k in keys if measures[k]["char_errors"] < base[k]["char_errors"]]
        regressed = [k for k in keys if measures[k]["char_errors"] > base[k]["char_errors"]]
        canary_lost = sorted(f"{k}#{w}" for k in keys for w, ok in base[k]["canary_correct"].items() if ok and not measures[k]["canary_correct"].get(w, False))
        hard_lost = sorted(f"{k}#{w}" for k in keys for w, ok in base[k]["hard_case_correct"].items() if ok and not measures[k]["hard_case_correct"].get(w, False))
        new_entity_errors = Counter()
        for k in keys:
            for kind, count in measures[k]["entities_wrong"].items():
                new_entity_errors[kind] += max(0, count - base[k]["entities_wrong"].get(kind, 0))
        per_pdf = defaultdict(lambda: Counter())
        for k in improved:
            per_pdf[k.split("|")[0]]["improved"] += 1
        for k in regressed:
            per_pdf[k.split("|")[0]]["regressed"] += 1
        tone = Counter()
        for k in keys:
            tone.update(measures[k]["tone"])
        summary[config] = {
            **(metrics(rows) if rows else {}),
            "improved": len(improved), "regressed": len(regressed), "unchanged": len(keys) - len(improved) - len(regressed),
            "identical_text_to_A0": sum(by_key[k][config]["text"] == by_key[k]["A0"]["text"] for k in keys),
            "sign_test": sign_test(len(improved), len(regressed)),
            "tone_and_modifier_errors": dict(tone.most_common()),
            "diacritic_char_errors": sum(v for d, v in tone.items() if d.startswith("tone_")),
            "zero_O_Q_errors": sum(measures[k]["zero_O_Q"] for k in keys),
            "one_I_U_errors": sum(measures[k]["one_I_U"] for k in keys),
            "entity_instances": dict(sum((measures[k]["entities"] for k in keys), Counter())),
            "entity_instances_with_error": dict(sum((measures[k]["entities_wrong"] for k in keys), Counter())),
            "new_entity_errors_vs_A0": dict(new_entity_errors),
            "canary_regressions": canary_lost, "hard_case_word_regressions": len(hard_lost),
            "per_pdf": {doc: dict(c) for doc, c in sorted(per_pdf.items())},
            "by_group": {group: {"improved": sum(document_group(k.split("|")[0]) == group for k in improved),
                                 "regressed": sum(document_group(k.split("|")[0]) == group for k in regressed)}
                         for group in ("born_digital", "scanned")},
        }
        if config != "A0":
            for k in improved + regressed:
                pairs.append({"set": name, "config": config, "key": k, "reference": references[k],
                              "baseline": by_key[k]["A0"]["text"], "candidate": by_key[k][config]["text"],
                              "baseline_char_errors": base[k]["char_errors"], "candidate_char_errors": measures[k]["char_errors"],
                              "status": "improved" if k in improved else "regressed",
                              "candidate_spans": [f"{s['reference']}→{s['hypothesis']}" for s in error_spans(references[k], by_key[k][config]["text"])],
                              "baseline_spans": [f"{s['reference']}→{s['hypothesis']}" for s in error_spans(references[k], by_key[k]["A0"]["text"])],
                              "masked_pixels": by_key[k][config]["masked_pixels"],
                              "neighbour_pixels_in_band": by_key[k][config]["neighbour_pixels_in_band"]})
    return summary, pairs


def unlabelled_changes(keys: list[str], by_key: dict, configs: list[str]) -> dict:
    """No reference: how often a candidate changes the baseline text, canaries and number fields."""
    number = re.compile(r"[0-9A-Za-zĐđ./-]*\d[0-9A-Za-zĐđ./-]*/[0-9A-Za-zĐđ./-]+")
    result = {}
    for config in configs[1:]:
        changed = [k for k in keys if by_key[k][config]["text"] != by_key[k]["A0"]["text"]]
        canary, numbers, per_pdf = [], [], Counter()
        for k in changed:
            base, cand = by_key[k]["A0"]["text"], by_key[k][config]["text"]
            per_pdf[k.split("|")[0]] += 1
            base_words, cand_words = nfc(base).split(), nfc(cand).split()
            ops = alignment([w.lower() for w in base_words], [w.lower() for w in cand_words])
            same = {i for op, i, _ in ops if op == "equal"}
            for i, word in enumerate(base_words):
                plain = re.sub(r"^\W+|\W+$", "", word.lower())
                if i not in same and plain in CANARIES:
                    canary.append(f"{k}#{plain}")
                if i not in same and number.fullmatch(word.strip(";,.:()")):
                    numbers.append(f"{k}#{word}")
        result[config] = {"lines": len(keys), "changed_lines": len(changed), "changed_fraction": round(len(changed) / len(keys), 4),
                          "baseline_canary_words_changed": canary, "baseline_number_tokens_changed": numbers,
                          "changed_by_pdf": dict(sorted(per_pdf.items()))}
    return result


def select(dev: dict, configs: list[str]) -> dict:
    """The pre-registered rule, applied to DEV only."""
    base = dev["A0"]
    candidates = []
    for config in configs[1:]:
        r = dev[config]
        reasons = []
        if not r["char_errors"] < base["char_errors"]:
            reasons.append("no fewer character errors than A0")
        if not (r["improved"] > r["regressed"] and r["sign_test"]["p_one_sided_improvement"] < 0.05):
            reasons.append("improvement not significant (sign test)")
        if r["canary_regressions"]:
            reasons.append("canary regression")
        if any(r["new_entity_errors_vs_A0"].values()):
            reasons.append("new document-number/date/agency/e-mail error")
        candidates.append({"config": config, "eligible": not reasons, "reasons": reasons, "cer": r["cer"],
                           "regressed": r["regressed"]})
    eligible = sorted((c for c in candidates if c["eligible"]), key=lambda c: (c["cer"], c["regressed"]))
    return {"rule": "pre-registered (preregistration.json)", "candidates": candidates,
            "selected": eligible[0]["config"] if eligible else None}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--v1-dir", type=Path, default=REPO / "demo/local_pdf_ocr/quality_work/vietdoc_5pdf_review40_eval_v1")
    parser.add_argument("--labels-v1", type=Path, required=True)
    args = parser.parse_args(argv)
    work = args.work_dir
    targets = [work / n for n in ("crop_candidate_metrics.json", "crop_experiment_matrix.csv", "paired_lines.jsonl")]
    if any(t.exists() for t in targets):
        raise ValueError("STOP: evaluation outputs already exist")
    prereg = json.loads((work / "preregistration.json").read_text(encoding="utf-8"))
    configs = [c["config"] for c in prereg["configs"]]
    sources = json.loads((work / "experiment_sources.json").read_text(encoding="utf-8"))["sources"]
    by_key, manifests = load_runs(work / "runs")
    # Documents are split across runs by page: every line of every source needs every arm.
    lines_seen = Counter(k.split("|")[0] for k in by_key)
    short = {s["document"]: (lines_seen.get(s["document"], 0), s["lines"]) for s in sources
             if lines_seen.get(s["document"], 0) != s["lines"]}
    if short or any(set(v) != set(configs) for v in by_key.values()):
        raise ValueError(f"STOP: runs incomplete (document: lines run, lines expected): {short}")
    # Canaries that regressed before are tracked even when hard_cases.txt does not list them.
    agencies, entries = agency_names(), sorted(set(hard_case_entries()) | set(CANARIES))
    references = human_references(args.v1_dir, args.labels_v1, REPO / "demo/local_pdf_ocr/quality_work")
    tl_sets, tl_reasons = text_layer_sets(sources)
    references.update(tl_sets)
    sets, all_pairs = {}, []
    for name in ("DEV", "REG-H40", "REG-H72", "REG-H5", "REG-TL"):
        sets[name], pairs = evaluate_set(name, references[name], by_key, configs, agencies, entries)
        all_pairs += pairs
    regression_keys = sorted(k for k in by_key if by_key[k]["A0"]["set"] != "dev2_born_digital")
    unlabelled = unlabelled_changes(regression_keys, by_key, configs)
    selection = select(sets["DEV"], configs)
    report = {
        "schema": "crop_candidate_metrics_v1", "configs": prereg["configs"], "runs": manifests,
        "reference_sources": {"DEV": "PDF text layer (dev2)", "REG-H40": "human labels v1, trusted only",
                              "REG-H72": "human labels review_01", "REG-H5": "human labels review_numbers_02",
                              "REG-TL": "PDF text layer (old8 + new5)", "text_layer_filter_counts": tl_reasons},
        "normalization": "NFC; micro Levenshtein CER/WER; no case folding or punctuation removal",
        "sets": sets, "unlabelled_regression_lines": unlabelled, "selection_on_dev": selection,
        "blind_evaluation": "NOT EVALUATED (no blind set exists; 30.signed.pdf reserved untouched)",
    }
    (work / "crop_candidate_metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with (work / "paired_lines.jsonl").open("x", encoding="utf-8") as stream:
        for pair in all_pairs:
            stream.write(json.dumps(pair, ensure_ascii=False) + "\n")
    with (work / "crop_experiment_matrix.csv").open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["config", "arm", "pad_top_px", "pad_bottom_px", "pad_horizontal_px", "mask_neighbours",
                         *[f"{s}_{m}" for s in sets for m in ("lines", "exact", "cer", "wer", "improved", "regressed", "p_one_sided")],
                         "dev_eligible", "dev_selected", "dev_reasons", "regression_lines_changed_vs_A0",
                         "canary_regressions_all_sets", "new_key_field_errors_all_sets"])
        for c in prereg["configs"]:
            name = c["config"]
            row = [name, c["arm"], c["pad_top_px"], c["pad_bottom_px"], c["pad_horizontal_px"], c["mask_neighbours"]]
            for s in sets:
                r = sets[s][name]
                row += [r.get("lines"), r.get("exact_lines"), round(r.get("cer", 0), 6), round(r.get("wer", 0), 6),
                        r["improved"], r["regressed"], r["sign_test"]["p_one_sided_improvement"]]
            pick = next((x for x in selection["candidates"] if x["config"] == name), None)
            row += [pick["eligible"] if pick else "baseline", name == selection["selected"], "; ".join(pick["reasons"]) if pick else "",
                    unlabelled.get(name, {}).get("changed_lines", 0),
                    sum(len(sets[s][name]["canary_regressions"]) for s in sets),
                    sum(sum(sets[s][name]["new_entity_errors_vs_A0"].values()) for s in sets)]
            writer.writerow(row)
    print(json.dumps({"selected": selection["selected"], "dev": {c: (sets["DEV"][c]["char_errors"], sets["DEV"][c]["improved"], sets["DEV"][c]["regressed"]) for c in configs}}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Paired A0 / H1 scoring against independent human references, with key-field regression statistics.

Pure functions: no file is read here. ``score`` takes one row per scored line,
{"key", "document", "group", "sets", "reference", "a0", "h1"}, and returns the
metrics, the per-line pairs and every key-field change. ``verdict`` applies the
frozen criteria (blind_criteria_v1.json). References are human transcriptions;
the PDF text layer is never one.
"""
from __future__ import annotations

import math
import random
from collections import Counter, defaultdict

from demo.local_pdf_ocr.quality.benchmark import distance, nfc
from demo.local_pdf_ocr.quality.vietdoc_review40 import entity_spans, error_spans
from experiments.crop_geometry.evaluate import date_spans, sign_test

KEY_FIELDS = ("doc_number", "email", "agency_name", "date")


def binomial_upper_bound(k: int, n: int, confidence: float = 0.95) -> float:
    """Exact (Clopper-Pearson) one-sided upper bound of a proportion with k events in n."""
    if n == 0:
        return 1.0
    if k >= n:
        return 1.0

    def cdf(p: float) -> float:  # P(X <= k | n, p), in log space so large n cannot overflow
        lp, lq = math.log(p), math.log1p(-p)
        return sum(math.exp(math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * lp + (n - i) * lq)
                   for i in range(k + 1))

    low, high = k / n, 1.0
    for _ in range(100):
        middle = (low + high) / 2
        if cdf(middle) > 1 - confidence:
            low = middle
        else:
            high = middle
    return high


def key_field_errors(reference: str, hypothesis: str, agencies: list[str]) -> tuple[list[dict], set[tuple]]:
    """Key-field instances of the reference, and the ones an edit of the hypothesis touches."""
    ref, hyp = nfc(reference), nfc(hypothesis)
    spans = error_spans(ref, hyp)
    entities = [e for e in entity_spans(ref, agencies) + date_spans(ref) if e["type"] in KEY_FIELDS]
    wrong = set()
    for entity in entities:
        start, end = entity["start"], entity["end"]
        if any((s["ref_start"] < end and s["ref_end"] > start) or (s["ref_start"] == s["ref_end"] and start <= s["ref_start"] <= end)
               for s in spans):
            wrong.add((entity["type"], start, end))
    return entities, wrong


def pair_line(row: dict, agencies: list[str]) -> dict:
    ref, a0, h1 = nfc(row["reference"]), nfc(row["a0"]), nfc(row["h1"])
    entities, a0_wrong = key_field_errors(ref, a0, agencies)
    _, h1_wrong = key_field_errors(ref, h1, agencies)
    a0_errors, h1_errors = distance(ref, a0), distance(ref, h1)
    return {
        **{k: row[k] for k in ("key", "document", "group", "sets")},
        "chars": len(ref), "words": len(ref.split()),
        "a0_char_errors": a0_errors, "h1_char_errors": h1_errors,
        "a0_word_errors": distance(ref.split(), a0.split()), "h1_word_errors": distance(ref.split(), h1.split()),
        "a0_exact": ref == a0, "h1_exact": ref == h1, "h1_differs": a0 != h1,
        "status": "improved" if h1_errors < a0_errors else "regressed" if h1_errors > a0_errors else "unchanged",
        "key_fields": [{"type": e["type"], "text": e["text"], "a0_wrong": (e["type"], e["start"], e["end"]) in a0_wrong,
                        "h1_wrong": (e["type"], e["start"], e["end"]) in h1_wrong} for e in entities],
    }


def summarize(pairs: list[dict]) -> dict:
    if not pairs:
        return {"lines": 0}
    chars, words = sum(p["chars"] for p in pairs), sum(p["words"] for p in pairs)
    improved = sum(p["status"] == "improved" for p in pairs)
    regressed = sum(p["status"] == "regressed" for p in pairs)
    changed = sum(p["h1_differs"] for p in pairs)
    fields = {}
    for kind in KEY_FIELDS:
        instances = [f for p in pairs for f in p["key_fields"] if f["type"] == kind]
        fields[kind] = {"instances": len(instances), "a0_wrong": sum(f["a0_wrong"] for f in instances),
                        "h1_wrong": sum(f["h1_wrong"] for f in instances),
                        "newly_wrong_under_h1": sum(f["h1_wrong"] and not f["a0_wrong"] for f in instances),
                        "fixed_by_h1": sum(f["a0_wrong"] and not f["h1_wrong"] for f in instances)}
    return {
        "lines": len(pairs), "reference_chars": chars, "reference_words": words,
        "a0": {"char_errors": sum(p["a0_char_errors"] for p in pairs), "cer": sum(p["a0_char_errors"] for p in pairs) / chars if chars else None,
               "wer": sum(p["a0_word_errors"] for p in pairs) / words if words else None, "exact_lines": sum(p["a0_exact"] for p in pairs)},
        "h1": {"char_errors": sum(p["h1_char_errors"] for p in pairs), "cer": sum(p["h1_char_errors"] for p in pairs) / chars if chars else None,
               "wer": sum(p["h1_word_errors"] for p in pairs) / words if words else None, "exact_lines": sum(p["h1_exact"] for p in pairs)},
        "lines_h1_differs": changed, "improved": improved, "regressed": regressed,
        "unchanged": len(pairs) - improved - regressed,
        "sign_test": sign_test(improved, regressed),
        "regression_rate_on_changed": regressed / changed if changed else None,
        "regression_rate_upper95": binomial_upper_bound(regressed, changed) if changed else None,
        "key_fields": fields,
    }


def cluster_bootstrap(pairs: list[dict], resamples: int = 10_000, seed: int = 20261017) -> dict:
    """95% percentile interval of (A0 - H1) character errors per reference character, resampling PDFs."""
    by_document = defaultdict(lambda: [0, 0, 0])
    for p in pairs:
        cell = by_document[p["document"]]
        cell[0] += p["a0_char_errors"]
        cell[1] += p["h1_char_errors"]
        cell[2] += p["chars"]
    documents = sorted(by_document)
    if len(documents) < 2:
        return {"documents": len(documents), "interval": None}
    rng = random.Random(seed)
    values = []
    for _ in range(resamples):
        sample = [by_document[rng.choice(documents)] for _ in documents]
        chars = sum(c[2] for c in sample)
        values.append((sum(c[0] for c in sample) - sum(c[1] for c in sample)) / chars if chars else 0.0)
    values.sort()
    return {"documents": len(documents), "resamples": resamples, "seed": seed,
            "delta_cer_a0_minus_h1": [values[int(0.025 * resamples)], values[int(0.975 * resamples) - 1]]}


def score(rows: list[dict], agencies: list[str]) -> dict:
    pairs = [pair_line(row, agencies) for row in rows]
    sets = sorted({s for p in pairs for s in p["sets"]})
    result = {
        "all": summarize(pairs),
        "by_set": {s: summarize([p for p in pairs if s in p["sets"]]) for s in sets},
        "by_group": {g: summarize([p for p in pairs if p["group"] == g]) for g in sorted({p["group"] for p in pairs})},
        "by_document": {d: summarize([p for p in pairs if p["document"] == d]) for d in sorted({p["document"] for p in pairs})},
        "bootstrap_changed": cluster_bootstrap([p for p in pairs if "changed" in p["sets"]]),
    }
    changes = [{"key": p["key"], "document": p["document"], "type": f["type"], "text": f["text"],
                "a0_wrong": f["a0_wrong"], "h1_wrong": f["h1_wrong"]}
               for p in pairs for f in p["key_fields"] if f["a0_wrong"] != f["h1_wrong"]]
    return {"metrics": result, "pairs": pairs, "key_field_changes": changes}


def verdict(primary: dict, sensitivity: dict | None, criteria: dict, integrity: dict, sufficiency_inputs: dict) -> dict:
    """Apply the frozen criteria. ``primary``/``sensitivity`` are score()["metrics"] dicts."""
    s = criteria["sufficiency"]
    sufficiency = {
        "min_pdfs": sufficiency_inputs["pdfs"] >= s["min_pdfs"],
        "min_born_digital_pdfs": sufficiency_inputs["born_digital_pdfs"] >= s["min_born_digital_pdfs"],
        "min_changed_lines_scored": primary["by_set"].get("changed", {}).get("lines", 0) >= s["min_changed_lines_scored"],
        "min_representative_lines_scored": primary["by_set"].get("representative", {}).get("lines", 0) >= s["min_representative_lines_scored"],
        "max_excluded_share": sufficiency_inputs["excluded_share"] <= s["max_excluded_share"],
    }

    def gates(metrics: dict) -> dict:
        changed = metrics["by_set"].get("changed", {"lines": 0})
        representative = metrics["by_set"].get("representative", {"lines": 0})
        scanned = metrics["by_group"].get("scanned", {"lines": 0})
        result = {
            "B1_changed_lines_improve": bool(changed["lines"]) and changed["h1"]["char_errors"] < changed["a0"]["char_errors"]
            and changed["improved"] > changed["regressed"]
            and changed["sign_test"]["p_one_sided_improvement"] < criteria["go"]["B1_sign_test_alpha"],
            "B2_regression_rate": bool(changed["lines"]) and changed["regression_rate_upper95"] is not None
            and changed["regression_rate_upper95"] <= criteria["go"]["B2_max_regression_rate_upper95"],
            "B3_no_new_key_field_errors": bool(metrics["all"]["lines"])
            and all(v["newly_wrong_under_h1"] == 0 for v in metrics["all"]["key_fields"].values()),
            "B4_scans_not_degraded": not scanned["lines"] or (scanned["h1"]["char_errors"] <= scanned["a0"]["char_errors"]
                                                              and scanned["regressed"] == 0),
            "B5_no_pdf_worse": all(d["h1"]["char_errors"] <= d["a0"]["char_errors"] for d in metrics["by_document"].values() if d["lines"]),
            "B6_representative_not_worse": bool(representative["lines"]) and representative["h1"]["cer"] <= representative["a0"]["cer"],
        }
        return result

    primary_gates = gates(primary)
    primary_gates["B7_integrity"] = all(integrity.values())
    sensitivity_gates = gates(sensitivity) if sensitivity else {}
    primary_gates["B8_label_sensitivity"] = bool(sensitivity_gates) and sensitivity_gates["B1_changed_lines_improve"] \
        and sensitivity_gates["B3_no_new_key_field_errors"]
    if not all(sufficiency.values()):
        outcome = "INSUFFICIENT_DATA"
    elif not all(v for k, v in primary_gates.items() if k != "B8_label_sensitivity"):
        outcome = "NO_GO"
    elif not primary_gates["B8_label_sensitivity"]:
        outcome = "INCONCLUSIVE"
    else:
        outcome = "GO_CANDIDATE_FOR_USER_DECISION"
    return {"verdict": outcome, "sufficiency": sufficiency, "gates": primary_gates, "sensitivity_gates": sensitivity_gates,
            "note": "Even GO_CANDIDATE needs an explicit user decision before any deployment."}

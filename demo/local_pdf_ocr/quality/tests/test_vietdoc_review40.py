"""Synthetic tests for the 40-line review-pack evaluation: no PDF, OCR model or private data."""
import base64
import csv
import hashlib
import io
import json
import random
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

from PIL import Image

from demo.local_pdf_ocr.quality import vietdoc_review40 as review40
from demo.local_pdf_ocr.quality.benchmark import distance
from demo.local_pdf_ocr.quality.e2e_regression import check_samples, compare_exports, run as run_e2e

AGENCIES = review40.agency_names(Path("missing.txt"))  # only the built-in extras
AGENCIES = sorted({*AGENCIES, "Bộ Văn hóa, Thể thao và Du lịch", "Văn phòng Chính phủ"}, key=len, reverse=True)

# (document, page, line, group, ocr, status, region, reference)
ROWS = [
    ("docA.signed.pdf", 1, 2, "diagnostic_targeted", "Email: tt@example.yn", "verified", "printed_text",
     "Email: tt@example.vn"),
    ("docA.signed.pdf", 1, 7, "representative_hash_selected", "Độc lập - Tự do - Hạnh phúc", "verified",
     "printed_text", "Độc lập - Tự do - Hạnh phúc"),
    ("docA.signed.pdf", 1, 9, "representative_hash_selected", "Căn cứ Nghi đinh số 12/2024/NĐ-CP", "verified",
     "printed_text", "Căn cứ Nghi đinh số 12/2024/NĐ-CP"),
    ("docB.signed.pdf", 2, 3, "representative_hash_selected", "Tiêu chuẩn và triển khai", "verified",
     "printed_text", "Tiêu chuẩn và triển khai"),
    ("docB.signed.pdf", 1, 10, "diagnostic_targeted", "Số: 5U/NQ-CP", "verified", "handwriting", "Số: 521/NQ-CP"),
    ("docB.signed.pdf", 3, 31, "diagnostic_targeted", "C#Q", "uncertain", "uncertain", None),
]


def png(seed: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (30 + seed, 12), (seed * 7 % 255, 90, 160)).save(buffer, format="PNG")
    return buffer.getvalue()


def build_pack(root: Path) -> tuple[Path, Path]:
    pack_dir, crops = root / "pack", root / "pack" / "crops"
    crops.mkdir(parents=True)
    samples, html_rows, labels, documents = [], [], [], {}
    for n, (document, page, line, group, ocr, status, region, reference) in enumerate(ROWS):
        identifier = f"{Path(document).stem}__p{page:03d}_l{line:03d}"
        data = png(n)
        (crops / f"{identifier}.png").write_bytes(data)
        sample = {
            "id": identifier, "document": document, "pdf_sha256": hashlib.sha256(document.encode()).hexdigest(),
            "source_ocr_json_sha256": "0" * 64, "page": page, "line_index": line,
            "polygon": [[0, 0], [30 + n, 0], [30 + n, 12], [0, 12]], "ocr_original": ocr,
            "image_sha256": hashlib.sha256(data).hexdigest(), "image_file": f"crops/{identifier}.png",
            "sample_group": group,
        }
        samples.append(sample)
        html_rows.append({**{k: v for k, v in sample.items() if k != "image_file"},
                          "image_data": "data:image/png;base64," + base64.b64encode(data).decode()})
        doc = documents.setdefault(document, {"document": document, "pdf_sha256": sample["pdf_sha256"], "pages": 3,
                                              "representative": 0, "diagnostic": 0})
        doc["representative" if group.startswith("representative") else "diagnostic"] += 1
        labels.append({**{k: sample[k] for k in review40.COPIED_FIELDS}, "id": identifier, "review": {
            "status": status, "region": region, "reference": reference,
            "verified_by_human": status == "verified", "original_ocr_unchanged": True}})
    manifest = {"status": "REVIEW_PACK_UNLABELED", "selection": "synthetic", "no_ground_truth_included": True,
                "no_model_rerun": True, "blind_test_used": False, "ocr_baseline_unchanged": True,
                "count": len(samples), "documents": list(documents.values()), "samples": samples}
    (pack_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    pack = {"pack_id": "a" * 64, "rows": html_rows}
    (pack_dir / "mo_review_40.html").write_text(
        f"<!doctype html><script>const PACK={json.dumps(pack, ensure_ascii=False)};</script>", encoding="utf-8")
    counts = Counter(row["review"]["status"] for row in labels)
    label_file = root / "labels.json"
    label_file.write_text(json.dumps({
        "schema": review40.LABEL_SCHEMA, "status": "LOCAL_REVIEW_ONLY_NO_AUTO_OCR_CHANGE", "pack_sha256": "a" * 64,
        "generated_at": "2026-10-16T00:00:00Z", "model_inference_performed": False, "blind_test_used": False,
        "auto_replace_approved": False, "summary": {"total": len(labels), "verified": counts["verified"],
                                                    "uncertain": counts["uncertain"]},
        "labels": labels}, ensure_ascii=False), encoding="utf-8")
    return pack_dir, label_file


def identifier(n: int) -> str:
    document, page, line = ROWS[n][:3]
    return f"{Path(document).stem}__p{page:03d}_l{line:03d}"


class AlignmentTests(unittest.TestCase):
    def test_span_costs_sum_to_levenshtein_distance(self):
        alphabet = "aăâđeêioôơuưyạịộếỉ01OQU /-"
        rng = random.Random(7)
        for _ in range(300):
            a = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 12)))
            b = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 12)))
            self.assertEqual(sum(s["cost"] for s in review40.error_spans(a, b)), distance(a, b))

    def test_categories_describe_vietnamese_edits(self):
        spans = review40.error_spans("Nghị định", "Nghi đinh")
        self.assertEqual(len(spans), 2)
        self.assertTrue(all("diacritic" in s["categories"] and "tone_dropped:nang" in s["details"] for s in spans))
        self.assertIn("tone_changed:hoi->sac", review40.error_spans("chuẩn", "chuấn")[0]["details"])
        self.assertIn("tone_changed:hoi->sac", review40.error_spans("triển", "triến")[0]["details"])
        van = review40.error_spans("VĂN", "VẪN")[0]["details"]
        self.assertIn("tone_added:nga", van)
        self.assertIn("modifier_changed:breve->circumflex", van)
        self.assertIn("zero_O_Q", review40.error_spans("QH15", "0H15")[0]["categories"])
        self.assertIn("zero_O_Q", review40.error_spans("QH16", "OH16")[0]["categories"])
        self.assertIn("one_U", review40.error_spans("521/NQ", "5U/NQ")[0]["categories"])
        self.assertIn("case", review40.error_spans("CỤC", "cỤC")[0]["categories"])
        self.assertEqual(review40.error_spans("vn", "yn")[0]["categories"], ["substitution_other"])
        self.assertEqual(review40.error_spans("đúng", "đúng"), [])

    def test_tone_placement_and_skeleton(self):
        self.assertEqual(review40.tone_key("hoá"), review40.tone_key("hóa"))
        self.assertNotEqual(review40.tone_key("định"), review40.tone_key("đinh"))
        self.assertEqual(review40.skeleton("Định"), review40.skeleton("đinh"))
        self.assertEqual(review40.decompose("ự"), ("u", "horn", "nang"))


class EntityTests(unittest.TestCase):
    def test_document_numbers_email_and_agencies_come_from_reference(self):
        found = review40.entity_spans("Số: 521/NQ-CP; (để b/c) Email: tt@example.vn", AGENCIES)
        self.assertEqual([(e["type"], e["text"]) for e in found],
                         [("doc_number", "521/NQ-CP"), ("email", "tt@example.vn")])
        found = review40.entity_spans("của Bộ trưởng Bộ Văn hóa, Thể thao và Du lịch.", AGENCIES)
        self.assertEqual([(e["type"], e["text"]) for e in found],
                         [("agency_name", "Bộ Văn hóa, Thể thao và Du lịch")])
        upper = review40.entity_spans("Cơ quan: VĂN PHÒNG CHÍNH PHỦ", AGENCIES)
        self.assertEqual(upper[0]["text"], "VĂN PHÒNG CHÍNH PHỦ")
        number = review40.entity_spans("Luật số 63/2025/QH15;", AGENCIES)
        self.assertEqual(number[0]["text"], "63/2025/QH15")


class CorpusScreenTests(unittest.TestCase):
    def counts(self, lines):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "real_train.tsv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream, delimiter="\t")
                writer.writerow(["id", "text"])
                writer.writerows([[str(n), line] for n, line in enumerate(lines)])
            return review40.corpus_counts([path])

    def test_flags_rare_diacritic_variant_but_not_common_words(self):
        counts, display, _ = self.counts(["Căn cứ Nghị định số 1"] * 4 + ["Bộ Khoa học và Công nghệ"] * 4
                                         + ["quy định"] * 40 + ["quy đinh"])  # one noisy training label
        index = review40.skeleton_index(counts)
        flags = review40.corpus_variant_flags("Căn cứ Nghi đinh số", counts, display, index)
        self.assertIn("Nghi đinh", [f["bigram"] for f in flags])
        self.assertEqual(review40.corpus_variant_flags("Công nghệ", counts, display, index), [])
        noisy = review40.corpus_variant_flags("các quy đinh", counts, display, index)
        self.assertEqual([(f["bigram"], f["corpus_count"]) for f in noisy], [("quy đinh", 1)])

    def test_blind_transcripts_are_refused(self):
        with self.assertRaisesRegex(ValueError, "blind"):
            review40.corpus_counts([Path("blind_test.tsv")])


class AuditAndMetricsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.pack_dir, self.labels = build_pack(self.root)
        self.no_corpus = mock.patch.object(review40, "CORPUS", ())
        self.no_corpus.start()

    def tearDown(self):
        self.no_corpus.stop()
        self.directory.cleanup()

    def audit(self, **extra):
        return review40.audit(self.pack_dir, self.labels, None, with_environment=False,
                              requested={identifier(2): "Gõ lại cụm 'Nghi đinh' đúng như ảnh."}, **extra)

    def test_partition_quarantines_requested_and_uncertain_only(self):
        report = self.audit()
        self.assertEqual(report["failed_checks"], [])
        self.assertIn("source_ocr_json", report["blocked_checks"])
        self.assertIn("audit_cases_csv", report["blocked_checks"])
        self.assertEqual(report["partition"]["pending_recheck"], [identifier(2)])
        self.assertEqual(report["partition"]["uncertain_excluded"], [identifier(5)])
        self.assertEqual(len(report["partition"]["trusted"]), 4)
        self.assertFalse(report["labels_modified"])

    def test_tampered_crop_and_foreign_labels_fail_closed(self):
        crop = self.pack_dir / "crops" / f"{identifier(1)}.png"
        crop.write_bytes(png(99))
        self.assertIn("crop_files_and_hashes", self.audit()["failed_checks"])
        data = json.loads(self.labels.read_text(encoding="utf-8"))
        data["pack_sha256"] = "b" * 64
        self.labels.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.assertIn("review_html_binding", self.audit()["failed_checks"])

    def test_unknown_requested_id_stops(self):
        with self.assertRaisesRegex(ValueError, "not in the pack"):
            review40.audit(self.pack_dir, self.labels, None, with_environment=False, requested={"nope": "?"})

    def test_metrics_exclude_uncertain_and_keep_trusted_separate(self):
        report = self.audit()
        labels = json.loads(self.labels.read_text(encoding="utf-8"))
        manifest = json.loads((self.pack_dir / "manifest.json").read_text(encoding="utf-8"))
        result = review40.baseline_metrics(labels, manifest, report)
        as_labeled = result["sets"]["as_labeled_verified"]["overall"]
        pairs = [(row[7], row[4]) for row in ROWS if row[5] == "verified"]
        self.assertEqual(as_labeled["lines"], 5)
        self.assertEqual(as_labeled["char_errors"], sum(distance(r, h) for r, h in pairs))
        self.assertEqual(as_labeled["exact_lines"], 3)
        trusted = result["sets"]["trusted"]
        self.assertEqual(trusted["overall"]["lines"], 4)
        self.assertNotIn(identifier(2), trusted["ids"])
        self.assertEqual(trusted["by_region"]["handwriting"]["lines"], 1)
        errors = trusted["error_analysis"]
        self.assertEqual(errors["entities"]["email"]["instances_with_error"], 1)
        self.assertEqual(errors["entities"]["doc_number"]["instances_with_error"], 1)
        self.assertIn("one_U", errors["spans_by_category"])
        bound = result["sensitivity_if_pending_labels_are_wrong"]
        self.assertEqual(bound["exact_lines_at_most"], 2)
        self.assertEqual(result["excluded_uncertain"], [identifier(5)])

    def test_recheck_csv_is_written_once(self):
        report = self.audit()
        labels = json.loads(self.labels.read_text(encoding="utf-8"))
        manifest = json.loads((self.pack_dir / "manifest.json").read_text(encoding="utf-8"))
        target = self.root / "manual_recheck_required.csv"
        self.assertEqual(review40.write_recheck_csv(target, report, labels, manifest, self.pack_dir), 2)
        with target.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual({r["id"] for r in rows}, {identifier(2), identifier(5)})
        self.assertTrue(all(r["in_trusted_set"] == "no" and r["reviewer_transcription"] == "" for r in rows))
        with self.assertRaises(FileExistsError):
            review40.write_recheck_csv(target, report, labels, manifest, self.pack_dir)


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.pack_dir, label_file = build_pack(root)
        with mock.patch.object(review40, "CORPUS", ()):
            self.report = review40.audit(self.pack_dir, label_file, None, with_environment=False)
        self.labels = json.loads(label_file.read_text(encoding="utf-8"))
        self.manifest = json.loads((self.pack_dir / "manifest.json").read_text(encoding="utf-8"))
        self.base = {identifier(n): row[4] for n, row in enumerate(ROWS)}

    def tearDown(self):
        self.directory.cleanup()

    def compare(self, predictions):
        return review40.compare_candidate(self.labels, self.manifest, self.report, predictions, "synthetic")

    def test_fixes_without_regressions_are_only_eligible_for_a_larger_trial(self):
        fixed = {**self.base, identifier(0): "Email: tt@example.vn"}
        result = self.compare(fixed)
        self.assertEqual(result["decision"], "ELIGIBLE_FOR_LARGER_REGRESSION_TRIAL_ONLY")
        self.assertTrue(result["not_blind"])
        self.assertFalse(result["baseline_outputs_modified"])

    def test_chuan_to_chuan_swap_is_a_regression_even_when_totals_improve(self):
        mixed = {**self.base, identifier(0): "Email: tt@example.vn",
                 identifier(4): "Số: 521/NQ-CP", identifier(3): "Tiêu chuấn và triến khai"}
        result = self.compare(mixed)
        self.assertEqual(result["decision"], "NO_GO")
        self.assertEqual(result["line_regressions"], [identifier(3)])
        self.assertEqual(len(result["new_hoi_to_sac_spans"]), 2)
        lost = result["hard_case_word_regressions"][0]["lost"]
        self.assertTrue(any(word.startswith("triển") for word in lost))
        self.assertTrue(any(word.startswith("chuẩn") for word in lost))

    def test_missing_or_unknown_predictions_fail_closed(self):
        partial = dict(self.base)
        partial.pop(identifier(1))
        with self.assertRaisesRegex(ValueError, "missing"):
            self.compare(partial)
        with self.assertRaisesRegex(ValueError, "unknown"):
            self.compare({**self.base, "extra": "x"})


class EvaluateCliTests(unittest.TestCase):
    def test_existing_report_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pack_dir, label_file = build_pack(root)
            output = root / "out"
            output.mkdir()
            (output / "baseline_metrics.json").write_text("{}", encoding="utf-8")
            before = hashlib.sha256(label_file.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "overwrite"):
                review40.main(["evaluate", "--pack-dir", str(pack_dir), "--labels", str(label_file),
                               "--output-dir", str(output)])
            self.assertEqual(hashlib.sha256(label_file.read_bytes()).hexdigest(), before)
            self.assertEqual((output / "baseline_metrics.json").read_text(encoding="utf-8"), "{}")


class EndToEndComparisonTests(unittest.TestCase):
    def export(self, text="Số: 1/QĐ", polygon=((1, 2), (5, 2), (5, 4), (1, 4))):
        return {"method": "vietocr_ocr", "pages": [{"page": 1, "width": 10, "height": 10, "lines": [
            {"line_index": 1, "polygon": [list(p) for p in polygon], "text": text, "hit_decoder_limit": False}],
            "reading_order": {"modified": False}, "header_split_experiment": {"enabled": True}}]}

    def test_compare_exports_ignores_number_types_but_reports_changes(self):
        same = self.export(polygon=((1.0, 2.0), (5.0, 2.0), (5.0, 4.0), (1.0, 4.0)))
        same["pages"][0]["reading_order"] = {"modified": False, "zones": [{"bbox": [356.0, 4.5]}]}
        stored = self.export()
        stored["pages"][0]["reading_order"] = {"modified": False, "zones": [{"bbox": [356, 4.5]}]}
        self.assertTrue(compare_exports(stored, same)["reproduced_exactly"])
        same["pages"][0]["reading_order"]["modified"] = True
        self.assertEqual(compare_exports(stored, same)["structure_mismatches"],
                         [{"page": 1, "field": "reading_order"}])
        changed = compare_exports(self.export(), self.export(text="Số: 7/QĐ", polygon=((1, 2), (6, 2), (6, 4), (1, 4))))
        self.assertFalse(changed["reproduced_exactly"])
        self.assertEqual(len(changed["text_mismatches"]), 1)
        self.assertEqual(len(changed["polygon_mismatches"]), 1)

    def test_sample_check_statuses(self):
        rerun = self.export()
        samples = [
            {"id": "a", "page": 1, "line_index": 1, "polygon": [[1, 2], [5, 2], [5, 4], [1, 4]], "ocr_original": "Số: 1/QĐ"},
            {"id": "b", "page": 1, "line_index": 1, "polygon": [[1, 2], [5, 2], [5, 4], [1, 4]], "ocr_original": "x"},
            {"id": "c", "page": 2, "line_index": 1, "polygon": [], "ocr_original": "x"},
        ]
        self.assertEqual([r["status"] for r in check_samples(rerun, samples)],
                         ["text_and_polygon_match", "text_mismatch", "line_missing_in_rerun"])

    def test_existing_output_directory_stops_before_any_model_import(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "overwrite"):
                run_e2e([], [], Path(directory))


if __name__ == "__main__":
    unittest.main()

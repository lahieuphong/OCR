"""Blind re-check queue and labels v2 builder: synthetic data only, no PDF or model."""
import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from demo.local_pdf_ocr.quality import gt_v2

OCR = "Căn cứ Nghi đinh số 12/2024/NĐ-CP"


def image(seed: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (40 + seed, 14), (240, 240, 240)).save(buffer, format="PNG")
    return buffer.getvalue()


def items():
    return [
        {"id": "a", "kind": "eval40", "required": True, "priority": "high", "document": "d.pdf", "page": 1,
         "line_index": 20, "image": image(0),
         "reveal": {"v1_label": OCR, "v1_status": "verified", "v1_region": "printed_text", "ocr_original": OCR,
                    "pdf_text_layer": "Căn cứ Nghị định số 12/2024/NĐ-CP", "evidence": "text layer"}},
        {"id": "b", "kind": "eval40", "required": True, "priority": "high", "document": "d.pdf", "page": 3,
         "line_index": 31, "image": image(1),
         "reveal": {"v1_label": None, "v1_status": "uncertain", "v1_region": "uncertain", "ocr_original": "C#Q",
                    "pdf_text_layer": None, "evidence": ""}},
        {"id": "c", "kind": "eval40", "required": False, "priority": "optional", "document": "d.pdf", "page": 1,
         "line_index": 7, "image": image(2),
         "reveal": {"v1_label": "Độc lập - Tự do - Hạnh phúc", "v1_status": "verified", "v1_region": "printed_text",
                    "ocr_original": "Độc lập - Tự do - Hạnh phúc", "pdf_text_layer": None, "evidence": ""}},
    ]


def labels_v1():
    def row(identifier, ocr, status, region, reference):
        return {"id": identifier, "document": "d.pdf", "ocr_original": ocr,
                "review": {"status": status, "region": region, "reference": reference,
                           "verified_by_human": status == "verified", "original_ocr_unchanged": True}}
    return {"schema": "vietdoc_holdout_manual_review_v1", "pack_sha256": "p" * 64, "generated_at": "x",
            "summary": {"total": 3, "verified": 2, "uncertain": 1},
            "labels": [row("a", OCR, "verified", "printed_text", OCR), row("b", "C#Q", "uncertain", "uncertain", None),
                       row("c", "Độc lập - Tự do - Hạnh phúc", "verified", "printed_text", "Độc lập - Tự do - Hạnh phúc")]}


class BlindQueueTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.result = gt_v2.write_queue(items(), self.root / "gt", "q1", "test")
        self.queue_path = Path(self.result["queue"])
        self.queue = json.loads(self.queue_path.read_text(encoding="utf-8"))
        self.labels = self.root / "labels_v1.json"
        self.labels.write_text(json.dumps(labels_v1(), ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self.directory.cleanup()

    def export(self, **changes):
        sha = {i["id"]: i["image_sha256"] for i in self.queue["items"]}
        data = {"schema": gt_v2.EXPORT_SCHEMA, "queue_id": "q1", "queue_sha256": self.result["queue_sha256"],
                "reviewer": "reviewer-1", "exported_at": "2026-10-17T09:00:00Z", "items": {
                    "a": {"image_sha256": sha["a"], "revealed_at": "2026-10-17T08:01:00Z",
                          "blind": {"text": "Căn cứ Nghị định số 12/2024/NĐ-CP", "region": "printed_text",
                                    "status": "typed", "locked_at": "2026-10-17T08:00:00Z"},
                          "final": {"choice": "keep", "status": "verified", "region": "printed_text",
                                    "text": "Căn cứ Nghị định số 12/2024/NĐ-CP", "note": "",
                                    "decided_at": "2026-10-17T08:02:00Z"}},
                    "b": {"image_sha256": sha["b"], "revealed_at": "2026-10-17T08:05:00Z",
                          "blind": {"text": "", "region": "uncertain", "status": "not_text",
                                    "locked_at": "2026-10-17T08:04:00Z"},
                          "final": {"choice": "not_text", "status": "not_text", "region": "stamp_artifact",
                                    "text": None, "note": "", "decided_at": "2026-10-17T08:06:00Z"}}}}
        for path, value in changes.items():
            target = data
            *keys, last = path.split(".")
            for key in keys:
                target = target[key]
            target[last] = value
        path = self.root / f"export_{len(list(self.root.glob('export_*')))}.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def build(self, export, name="out"):
        return gt_v2.build_labels_v2(self.labels, self.queue_path, export, self.root / name)

    def test_page_shows_no_ocr_label_or_text_layer_in_plain_text(self):
        html = Path(self.result["html"]).read_text(encoding="utf-8")
        for secret in (OCR, "Căn cứ Nghị định số 12/2024/NĐ-CP", "C#Q", "Độc lập - Tự do - Hạnh phúc"):
            self.assertNotIn(secret, html)
        self.assertIn("Khóa bản gõ mù", html)
        self.assertEqual(self.result["required"], 2)

    def test_queue_records_image_hashes_and_never_overwrites(self):
        self.assertEqual(self.queue["items"][0]["image_sha256"], hashlib.sha256(image(0)).hexdigest())
        with self.assertRaisesRegex(ValueError, "overwrite"):
            gt_v2.write_queue(items(), self.root / "gt", "q1", "test")

    def test_a_complete_valid_export_writes_labels_v2_without_touching_v1(self):
        before = self.labels.read_bytes()
        result = self.build(self.export())
        self.assertEqual(result["status"], "WRITTEN")
        self.assertEqual(self.labels.read_bytes(), before)
        v2 = json.loads((self.root / "out" / "labels_v2.json").read_text(encoding="utf-8"))
        by_id = {row["id"]: row["review"] for row in v2["labels"]}
        self.assertEqual(by_id["a"]["reference"], "Căn cứ Nghị định số 12/2024/NĐ-CP")
        self.assertEqual(by_id["a"]["v1_review"]["reference"], OCR)
        self.assertEqual((by_id["b"]["status"], by_id["b"]["region"]), ("uncertain", "stamp_artifact"))
        self.assertEqual(by_id["c"]["v2_provenance"], "v1_unchanged")
        self.assertEqual(v2["summary"]["changed"], 2)
        self.assertEqual(v2["derived_from"]["labels_v1_sha256"], hashlib.sha256(before).hexdigest())

    def test_missing_required_decision_is_blocked_and_writes_no_labels(self):
        export = self.export(**{"items.b.final": {}})
        result = self.build(export)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["required_without_valid_decision"], ["b"])
        self.assertFalse((self.root / "out" / "labels_v2.json").exists())
        self.assertTrue((self.root / "out" / "labels_v2_BLOCKED.json").exists())

    def test_invalid_decisions_are_blocked(self):
        cases = {
            "reveal_before_lock": {"items.a.revealed_at": "2026-10-17T07:00:00Z"},
            "changed_without_reason": {"items.a.final.text": "Căn cứ Nghị định số 12/2024/NĐ-CP ngày"},
            "unreadable_made_verified": {"items.b.blind.status": "unreadable", "items.b.final.status": "verified",
                                         "items.b.final.region": "printed_text", "items.b.final.text": "CAP"},
            "foreign_queue": {"queue_sha256": "0" * 64},
            "no_reviewer": {"reviewer": " "},
            "image_swapped": {"items.a.image_sha256": "1" * 64},
        }
        for name, change in cases.items():
            with self.subTest(name):
                result = self.build(self.export(**change), name=name)
                self.assertEqual(result["status"], "BLOCKED", name)
                self.assertFalse((self.root / name / "labels_v2.json").exists())

    def test_a_written_reason_allows_a_post_reveal_change(self):
        export = self.export(**{"items.a.final.text": "Căn cứ Nghị định số 12/2024/NĐ-CP ngày",
                                "items.a.final.choice": "edit", "items.a.final.note": "zoom 3x shows the word"})
        self.assertEqual(self.build(export)["status"], "WRITTEN")

    def test_existing_output_is_never_overwritten(self):
        self.build(self.export())
        with self.assertRaisesRegex(ValueError, "overwrite"):
            self.build(self.export())


class QuarantineReviewTests(unittest.TestCase):
    LABELS = {"t1": "quy định của", "t2": "quy đinh của", "t3": '"hàng giả" trong'}

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        train = [{"id": key, "kind": "train_label", "required": True, "priority": "high", "document": "doc",
                  "page": 1, "line_index": n, "image": image(5 + n),
                  "reveal": {"v1_label": text, "v1_status": "verified", "v1_region": "", "ocr_original": None,
                             "pdf_text_layer": None, "evidence": "corpus"}}
                 for n, (key, text) in enumerate(self.LABELS.items())]
        self.result = gt_v2.write_queue(train, self.root / "gt", "tq", "train")
        self.queue_path = Path(self.result["queue"])
        self.queue = json.loads(self.queue_path.read_text(encoding="utf-8"))
        self.quarantine = self.root / "label_quarantine.tsv"
        gt_v2.write_plain_tsv(self.quarantine, gt_v2.QUARANTINE_COLUMNS, [
            {"id": key, "split": "real_train", "reason": "diacritic_variant_screen", "status": "open",
             "opened": "2026-10-16", "note": "pending"} for key in self.LABELS])
        self.manifest = self.root / "real_train.tsv"
        gt_v2.write_plain_tsv(self.manifest, ("id", "text"), [{"id": k, "text": v} for k, v in self.LABELS.items()])

    def tearDown(self):
        self.directory.cleanup()

    def export(self, **overrides):
        sha = {i["id"]: i["image_sha256"] for i in self.queue["items"]}
        finals = {"t1": ("verified", "quy định của"), "t2": ("verified", "quy định của"), "t3": ("uncertain", None)}
        items = {}
        for key, (status, text) in finals.items():
            items[key] = {"image_sha256": sha[key], "revealed_at": "2026-10-17T08:01:00Z",
                          "blind": {"text": text or "", "region": "printed_text", "status": "typed",
                                    "locked_at": "2026-10-17T08:00:00Z"},
                          "final": {"choice": "keep" if status == "verified" else status, "status": status,
                                    "region": "printed_text" if status == "verified" else "uncertain",
                                    "text": text, "note": "", "decided_at": "2026-10-17T08:02:00Z"}}
        data = {"schema": gt_v2.EXPORT_SCHEMA, "queue_id": "tq", "queue_sha256": self.result["queue_sha256"],
                "reviewer": "reviewer-1", "exported_at": "2026-10-17T09:00:00Z", "items": items, **overrides}
        path = self.root / f"export_{len(list(self.root.glob('export_*')))}.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def review(self, export, name="out", apply=False):
        return gt_v2.quarantine_review(self.queue_path, export, self.quarantine, [self.manifest], self.root / name,
                                       apply=apply)

    def test_only_a_label_verified_as_it_stands_is_released(self):
        before = self.quarantine.read_bytes()
        report = self.review(self.export())
        self.assertEqual(report["released"], ["t1"])
        self.assertEqual(report["still_open"], ["t2", "t3"])
        self.assertEqual([c["id"] for c in report["corrections_proposed"]], ["t2"])
        self.assertEqual(self.quarantine.read_bytes(), before)  # no --apply: nothing changes
        _, proposed = gt_v2.read_plain_tsv(self.root / "out" / "label_quarantine.proposed.tsv")
        self.assertEqual({r["id"]: r["status"] for r in proposed}, {"t1": "resolved", "t2": "open", "t3": "open"})

    def test_apply_rewrites_the_quarantine_and_keeps_the_previous_copy(self):
        before = self.quarantine.read_bytes()
        report = self.review(self.export(), apply=True)
        self.assertTrue(report["quarantine_changed"])
        self.assertEqual((self.root / "out" / "label_quarantine.before.tsv").read_bytes(), before)
        _, rows = gt_v2.read_plain_tsv(self.quarantine)
        self.assertEqual([r["id"] for r in rows if r["status"] == "open"], ["t2", "t3"])

    def test_an_invalid_export_releases_nothing(self):
        before = self.quarantine.read_bytes()
        report = self.review(self.export(queue_sha256="0" * 64), apply=True)
        self.assertEqual((report["status"], report["released"]), ("BLOCKED", []))
        self.assertEqual(self.quarantine.read_bytes(), before)

    def test_a_label_changed_since_the_queue_stops(self):
        gt_v2.write_plain_tsv(self.manifest, ("id", "text"), [
            {"id": k, "text": v + (" x" if k == "t1" else "")} for k, v in self.LABELS.items()])
        with self.assertRaisesRegex(ValueError, "changed since the queue"):
            self.review(self.export())


class TextLayerReportTests(unittest.TestCase):
    def test_line_by_line_ocr_label_and_pdf_differences(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            integrity = {"samples": [
                {"id": "a", "document": "d.pdf", "page": 1, "line_index": 20, "sample_group": "diagnostic_targeted",
                 "text_layer": {"text_layer": "Căn cứ Nghị định số"}},
                {"id": "c", "document": "d.pdf", "page": 1, "line_index": 7, "sample_group": "representative",
                 "text_layer": None}]}
            (root / "label_integrity_report.json").write_text(json.dumps(integrity, ensure_ascii=False), encoding="utf-8")
            data = copy.deepcopy(labels_v1())
            data["labels"][0]["ocr_original"] = data["labels"][0]["review"]["reference"] = "Căn cứ Nghi đinh số"
            (root / "labels.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            report = gt_v2.textlayer_report(root, root / "labels.json")
        self.assertEqual(report["lines"], 1)
        row = report["rows"][0]
        self.assertEqual((row["ocr_vs_label_char_errors"], row["ocr_vs_pdf_char_errors"]), (0, 2))
        self.assertEqual(row["delta_char_errors_pdf_minus_label"], 2)
        self.assertEqual(report["label_disagrees_with_pdf"], ["a"])
        self.assertEqual(report["ocr_vs_pdf_text"]["char_errors"], 2)


if __name__ == "__main__":
    unittest.main()

"""Correction addendum for a locked blind-review export: synthetic PDF, queue and exports only."""
import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from demo.local_pdf_ocr.quality import gt_v2, gt_v2_addendum as addendum_tool
from demo.local_pdf_ocr.quality.tests.test_gt_v2 import OCR, image, items, labels_v1

# PyMuPDF renders the synthetic PDF behind the addendum page; the model-free CI job installs Pillow only.
# Only its absence skips the page tests: an installed but broken PyMuPDF still fails at import.
HAVE_PYMUPDF = importlib.util.find_spec("pymupdf") is not None
if HAVE_PYMUPDF:
    import pymupdf as fitz
needs_pymupdf = unittest.skipUnless(HAVE_PYMUPDF, "optional dependency PyMuPDF is not installed")

SECRETS = (OCR, "Căn cứ Nghị định số 12/2024/NĐ-CP", "C#Q")  # OCR / text layer of the synthetic queue


def export_data(result) -> dict:
    queue = json.loads(Path(result["queue"]).read_text(encoding="utf-8"))
    sha = {i["id"]: i["image_sha256"] for i in queue["items"]}

    def typed(identifier, text, status="verified", region="printed_text", minute=0):
        return {"image_sha256": sha[identifier], "revealed_at": f"2026-10-17T08:0{minute}:30.000Z",
                "blind": {"text": text, "region": region, "status": "typed", "locked_at": f"2026-10-17T08:0{minute}:00.000Z"},
                "final": {"choice": "keep", "status": status, "region": region, "text": text, "note": "",
                          "decided_at": f"2026-10-17T08:0{minute}:40.000Z"}}
    data = {"schema": gt_v2.EXPORT_SCHEMA, "queue_id": "q1", "queue_sha256": result["queue_sha256"],
            "reviewer": "reviewer-1", "exported_at": "2026-10-17T09:00:00.000Z",
            "items": {"a": typed("a", "Căn cứ Nghị đinh số 12/2024/NĐ-CP"), "c": typed("c", "Độc lập - Tự do - Hạnh phúc", minute=2)}}
    data["items"]["b"] = {"image_sha256": sha["b"], "revealed_at": "2026-10-17T08:01:30.000Z",
                          "blind": {"text": "", "region": "uncertain", "status": "not_text", "locked_at": "2026-10-17T08:01:00.000Z"},
                          "final": {"choice": "not_text", "status": "not_text", "region": "stamp_artifact", "text": None, "note": "",
                                    "decided_at": "2026-10-17T08:01:40.000Z"}}
    return data


class AddendumTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.result = gt_v2.write_queue(items(), self.root / "gt", "q1", "test")
        self.queue_path, self.html = Path(self.result["queue"]), Path(self.result["html"])
        self.labels = self.root / "labels_v1.json"
        self.labels.write_text(json.dumps(labels_v1(), ensure_ascii=False), encoding="utf-8")
        self.export_path = self.root / "q1_blind_review_export.json"
        self.export_path.write_text(json.dumps(export_data(self.result), ensure_ascii=False, indent=2), encoding="utf-8")
        self.export_bytes = self.export_path.read_bytes()
        if HAVE_PYMUPDF:  # only the page tests read this PDF
            pdf = self.root / "pdfs" / "d.pdf"
            pdf.parent.mkdir()
            doc = fitz.open()
            for _ in range(3):
                doc.new_page(width=300, height=200).insert_text((20, 40), "Dòng chữ mẫu để render", fontsize=11)
            doc.save(pdf)
            pdf_sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
            polygon = [[30, 50], [400, 50], [400, 90], [30, 90]]
            self.pack = self.root / "pack"
            self.pack.mkdir()
            (self.pack / "manifest.json").write_text(json.dumps({"samples": [
                {"id": i["id"], "document": "d.pdf", "page": i["page"], "line_index": i["line_index"], "polygon": polygon,
                 "pdf_sha256": pdf_sha} for i in items()]}), encoding="utf-8")
            self.pdf_dir = pdf.parent

    def page(self, ids=("a", "b"), name="addendum"):
        result = addendum_tool.write_page(self.queue_path, self.html, self.export_path, self.pack, self.pdf_dir, list(ids),
                                          self.root / name)
        return Path(result["page"]), json.loads(Path(result["page"]).read_text(encoding="utf-8")), result

    def addendum(self, page: dict, page_path: Path, decisions: dict, **overrides) -> Path:
        """What the page's script exports, built from the page config."""
        items_out = {}
        for item in page["items"]:
            if item["id"] not in decisions:
                continue
            action, text, region, reason = decisions[item["id"]]
            items_out[item["id"]] = {"image_sha256": item["image_sha256"], "previous_blind": item["previous_blind"],
                                     "previous_final": item["previous_final"], "action": action, "text": text,
                                     "region": region, "reason": reason, "opened_at": "2026-10-17T10:00:00.000Z",
                                     "decided_at": "2026-10-17T10:05:00.000Z",
                                     "history": [{"action": action, "text": text, "region": region, "reason": reason,
                                                  "decided_at": "2026-10-17T10:05:00.000Z"}]}
        data = {"schema": addendum_tool.ADDENDUM_SCHEMA, "page_id": page["page_id"],
                "page_sha256": hashlib.sha256(page_path.read_bytes()).hexdigest(), "queue_id": "q1",
                "queue_sha256": self.result["queue_sha256"], "base_export_sha256": hashlib.sha256(self.export_bytes).hexdigest(),
                "base_export_file": self.export_path.name, "reviewer": "reviewer-1", "page_opened_at": "2026-10-17T10:00:00.000Z",
                "exported_at": "2026-10-17T10:06:00.000Z", "items": items_out, **overrides}
        path = self.root / f"addendum_{len(list(self.root.glob('addendum_*.json')))}.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def build(self, page_path, addendum_path, name="labels"):
        return addendum_tool.build(self.labels, self.queue_path, self.export_path, page_path, addendum_path, self.root / name)

    def test_export_check_and_byte_identical_evidence(self):
        report = addendum_tool.check_export(self.queue_path, self.export_path)
        self.assertTrue(report["valid"] and report["complete"])
        self.assertEqual((report["queue_items"], report["export_items"], report["valid_decisions"]), (3, 3, 3))
        self.assertEqual(report["final_status"], {"verified": 2, "not_text": 1})
        evidence = addendum_tool.keep_evidence(self.export_path, self.root / "out")
        self.assertEqual(Path(evidence["evidence"]).read_bytes(), self.export_bytes)
        self.assertEqual(self.export_path.read_bytes(), self.export_bytes)
        with self.assertRaisesRegex(ValueError, "overwrite"):
            addendum_tool.keep_evidence(self.export_path, self.root / "out")
        broken = json.loads(self.export_bytes)
        broken["queue_sha256"] = "0" * 64
        self.export_path.write_text(json.dumps(broken), encoding="utf-8")
        self.assertFalse(addendum_tool.check_export(self.queue_path, self.export_path)["valid"])

    @needs_pymupdf
    def test_page_holds_only_the_chosen_lines_and_no_machine_text(self):
        page_path, page, result = self.page()
        self.assertEqual([i["id"] for i in page["items"]], ["a", "b"])
        self.assertEqual(page["base_export_sha256"], hashlib.sha256(self.export_bytes).hexdigest())
        html = Path(result["html"]).read_text(encoding="utf-8")
        for secret in SECRETS:
            self.assertNotIn(secret, html)
        self.assertIn("data:image/png;base64,", html)
        self.assertEqual(page["items"][0]["image_sha256"], hashlib.sha256(image(0)).hexdigest())
        with self.assertRaisesRegex(ValueError, "overwrite"):
            self.page()
        with self.assertRaisesRegex(ValueError, "distinct items"):
            self.page(ids=("a", "zzz"), name="other")

    @needs_pymupdf
    def test_a_valid_addendum_builds_labels_v2_and_keeps_every_other_line(self):
        page_path, page, _ = self.page()
        path = self.addendum(page, page_path, {"a": ("correct", "Căn cứ Nghị định số 12/2024/NĐ-CP", "printed_text", "zoom 3x: dấu nặng"),
                                               "b": ("uncertain", None, "uncertain", "không chắc là dấu mộc")})
        report = self.build(page_path, path)
        self.assertEqual(report["status"], "WRITTEN")
        self.assertEqual(self.export_path.read_bytes(), self.export_bytes)  # the export is only read
        labels = json.loads((self.root / "labels" / "labels_v2.json").read_text(encoding="utf-8"))
        rows = {r["id"]: r["review"] for r in labels["labels"]}
        self.assertEqual(rows["a"]["reference"], "Căn cứ Nghị định số 12/2024/NĐ-CP")
        self.assertEqual(rows["a"]["blind_transcription"], "Căn cứ Nghị đinh số 12/2024/NĐ-CP")  # blind history kept
        self.assertEqual(rows["a"]["correction_addendum"]["superseded_final"]["text"], "Căn cứ Nghị đinh số 12/2024/NĐ-CP")
        self.assertTrue(rows["a"]["correction_addendum"]["blind_entry_unchanged"])
        self.assertEqual((rows["b"]["status"], rows["b"]["region"]), ("uncertain", "uncertain"))
        reference = gt_v2.build_labels_v2(self.labels, self.queue_path, self.export_path, self.root / "export_only")
        self.assertEqual(reference["status"], "WRITTEN")
        plain = {r["id"]: r for r in json.loads((self.root / "export_only" / "labels_v2.json").read_text(encoding="utf-8"))["labels"]}
        built = {r["id"]: r for r in labels["labels"]}
        self.assertEqual(built["c"], plain["c"])  # outside the addendum: identical field for field
        self.assertEqual(labels["derived_from"]["export_sha256"], hashlib.sha256(self.export_bytes).hexdigest())
        self.assertEqual((labels["summary"]["addendum_corrected"], labels["summary"]["addendum_uncertain"]), (1, 1))

    @needs_pymupdf
    def test_confirm_keeps_the_final_decision(self):
        page_path, page, _ = self.page()
        path = self.addendum(page, page_path, {"a": ("confirm", None, "printed_text", "đúng như đã gõ"),
                                               "b": ("confirm", None, "stamp_artifact", "đúng là dấu mộc")})
        self.assertEqual(self.build(page_path, path)["status"], "WRITTEN")
        rows = {r["id"]: r["review"] for r in json.loads((self.root / "labels" / "labels_v2.json").read_text(encoding="utf-8"))["labels"]}
        self.assertEqual(rows["a"]["reference"], "Căn cứ Nghị đinh số 12/2024/NĐ-CP")
        self.assertEqual(rows["a"]["correction_addendum"]["action"], "confirm")

    @needs_pymupdf
    def test_invalid_addenda_build_nothing(self):
        page_path, page, _ = self.page()
        good = {"a": ("correct", "Căn cứ Nghị định số 12/2024/NĐ-CP", "printed_text", "lý do"),
                "b": ("uncertain", None, "uncertain", "lý do")}
        tampered = copy.deepcopy(page)
        tampered["items"][0]["previous_final"]["text"] = "khác"
        cases = {
            "other_export": (good, {"base_export_sha256": "0" * 64}),
            "no_reviewer": (good, {"reviewer": " "}),
            "missing_line": ({"a": good["a"]}, {}),
            "no_reason": ({**good, "a": ("correct", "Căn cứ Nghị định số 12/2024/NĐ-CP", "printed_text", " ")}, {}),
            "same_text_as_correct": ({**good, "a": ("correct", "Căn cứ Nghị đinh số 12/2024/NĐ-CP", "printed_text", "x")}, {}),
            "unreadable_made_verified": ({**good, "b": ("correct", "CAP", "printed_text", "x")}, {}),
            "before_the_export": (good, {"items": None}),
        }
        for name, (decisions, overrides) in cases.items():
            with self.subTest(name):
                path = self.addendum(page, page_path, decisions, **{k: v for k, v in overrides.items() if k != "items"})
                if name == "before_the_export":
                    data = json.loads(path.read_text(encoding="utf-8"))
                    for entry in data["items"].values():
                        entry["decided_at"] = "2026-10-17T08:30:00.000Z"
                    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                report = self.build(page_path, path, name=name)
                self.assertEqual(report["status"], "BLOCKED", name)
                self.assertFalse((self.root / name / "labels_v2.json").exists())
        stale = self.root / "stale_page.json"
        stale.write_text(json.dumps(tampered, ensure_ascii=False), encoding="utf-8")
        path = self.addendum(tampered, stale, good)
        self.assertEqual(self.build(stale, path, name="stale")["status"], "BLOCKED")
        self.assertEqual(self.export_path.read_bytes(), self.export_bytes)


if __name__ == "__main__":
    unittest.main()

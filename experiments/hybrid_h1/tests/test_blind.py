"""Blind-round tools end to end on synthetic PDFs built in memory: no real document, no model inference."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pymupdf as fitz

from demo.local_pdf_ocr.quality import gt_v2
from experiments.hybrid_h1 import blind
from experiments.hybrid_h1 import freeze as frozen

HERE = Path(__file__).resolve().parents[1]
CRITERIA = json.loads((HERE / "blind_criteria_v1.json").read_text(encoding="utf-8"))
LINES = {  # (what the page shows = what a careful reader types, what A0 read)
    "a.pdf": [("Email: thongtin@example.vn", "Email: thongtin@example.yn"), ("Hello world", "Hello world"),
              ("Ha Noi, ngay 08 thang 10", "Ha Noi, ngay 08 thang10")],
    "b.pdf": [("So: 125/QD-TTg", "So: 12S/QD-TTg"), ("Alpha beta gamma", "Alpha beta gamma")],
}


def fake_manifest():
    names = ("__init__.py", "gates.py", "hybrid.py")
    return {"_manifest_sha256": "f" * 64, "criteria": CRITERIA, "b1024": {"selected": "phase4_exp_b_width1024"},
            "files": {"candidate": {f"experiments/hybrid_h1/{n}": frozen.frozen_sha256(HERE / n) for n in names}}}


def make_pdf(folder: Path, name: str, lines, model="phase4_exp_b_width1024"):
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    a0_lines = []
    for index, (truth, a0) in enumerate(lines, 1):
        y = 30 * index
        page.insert_text((20, y), truth, fontsize=11)
        boxes = [w[:4] for w in page.get_text("words") if y - 12 < (w[1] + w[3]) / 2 < y + 3]
        x0, y0 = min(b[0] for b in boxes) * 2 - 2, min(b[1] for b in boxes) * 2 - 2
        x1, y1 = max(b[2] for b in boxes) * 2 + 2, max(b[3] for b in boxes) * 2 + 2
        a0_lines.append({"line_index": index, "polygon": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "text": a0,
                         "hit_decoder_limit": False})
    pdf = folder / name
    doc.save(pdf)
    text = "\n".join(line["text"] for line in a0_lines)
    export = {"method": "vietocr_ocr", "model": model, "detection_model": "PP-OCRv6_medium_det",
              "header_split_enabled": True, "page_count": 1, "line_count": len(lines), "elapsed_ms": 1, "text": text,
              "pages": [{"page": 1, "width": 600, "height": 400, "lines": a0_lines, "text": text, "elapsed_ms": 1}]}
    a0 = folder / f"{Path(name).stem}.rerun.json"
    a0.write_text(json.dumps(export, ensure_ascii=False), encoding="utf-8")
    return pdf, a0


def export_for(queue_path: Path, truth: dict, reviewer="reviewer-1") -> dict:
    queue = json.loads(queue_path.read_bytes())
    items = {}
    for item in queue["items"]:
        text = truth[(item["document"], item["line_index"])]
        items[item["id"]] = {"image_sha256": item["image_sha256"], "revealed_at": "2026-10-20T08:01:00Z",
                             "blind": {"text": text, "region": "printed_text", "status": "typed", "locked_at": "2026-10-20T08:00:00Z"},
                             "final": {"choice": "keep", "status": "verified", "region": "printed_text", "text": text,
                                       "note": "", "decided_at": "2026-10-20T08:02:00Z"}}
    return {"schema": gt_v2.EXPORT_SCHEMA, "queue_id": queue["queue_id"],
            "queue_sha256": gt_v2.hashlib.sha256(queue_path.read_bytes()).hexdigest(), "reviewer": reviewer,
            "exported_at": "2026-10-20T09:00:00Z", "items": items}


class BlindRound(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.pairs = [make_pdf(self.root, name, lines) for name, lines in LINES.items()]
        self.non_blind = self.root / "experiment_sources.json"
        self.non_blind.write_text(json.dumps({"sources": []}), encoding="utf-8")
        self.round = self.root / "round"
        patcher = mock.patch.object(frozen, "require", side_effect=lambda path: fake_manifest())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.folder.cleanup)
        self.truth = {(name, i): truth for name, lines in LINES.items() for i, (truth, _) in enumerate(lines, 1)}

    def prepare(self):
        blind.register(Path("freeze.json"), self.round, self.pairs, non_blind=self.non_blind)
        with self.assertRaisesRegex(ValueError, "confirm-blind-round"):
            blind.run_h1(Path("freeze.json"), self.round)
        blind.run_h1(Path("freeze.json"), self.round, confirm=True)
        selection = blind.select(Path("freeze.json"), self.round)
        blind.queue(Path("freeze.json"), self.round)
        return selection

    def test_a_full_round_is_scored_once_from_blind_transcriptions(self):
        selection = self.prepare()
        self.assertEqual((selection["documents"], selection["changed"]), (2, 2))
        machine = {a0 for lines in LINES.values() for _, a0 in lines} | {t for lines in LINES.values() for t, _ in lines}
        pages = list((self.round / "queues").glob("*.review.html"))
        self.assertEqual(len(pages), 2)
        for page in pages:
            html = page.read_text(encoding="utf-8")
            for text in machine:
                self.assertNotIn(text, html)
            self.assertNotIn("representative", html)
        exports = self.round / "exports"
        exports.mkdir()
        queues = sorted((self.round / "queues").glob("*.queue.json"))
        (exports / "one.json").write_text(json.dumps(export_for(queues[0], self.truth), ensure_ascii=False), encoding="utf-8")
        blocked = blind.score(Path("freeze.json"), self.round)
        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertFalse((self.round / "score").exists())  # a blocked attempt does not use up the one scoring
        (exports / "two.json").write_text(json.dumps(export_for(queues[1], self.truth), ensure_ascii=False), encoding="utf-8")
        result = blind.score(Path("freeze.json"), self.round)
        self.assertEqual((result["status"], result["verdict"]), ("SCORED", "INSUFFICIENT_DATA"))
        report = json.loads((self.round / "score" / "blind_metrics.json").read_text(encoding="utf-8"))
        changed = report["primary"]["by_set"]["changed"]
        self.assertEqual((changed["lines"], changed["improved"], changed["regressed"]), (2, 2, 0))
        self.assertEqual(report["primary"]["all"]["key_fields"]["email"]["fixed_by_h1"], 1)
        self.assertTrue(all(report["integrity"].values()))
        with self.assertRaisesRegex(ValueError, "scored once"):
            blind.score(Path("freeze.json"), self.round)

    def test_used_or_foreign_documents_are_refused(self):
        self.non_blind.write_text(json.dumps({"sources": [{"pdf_sha256": frozen.sha256_file(self.pairs[0][0])}]}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "already used"):
            blind.register(Path("freeze.json"), self.round, self.pairs, non_blind=self.non_blind)
        result = blind.register(Path("freeze.json"), self.round, self.pairs, non_blind=self.non_blind, rehearsal=True)
        self.assertEqual(result["kind"], "REHEARSAL_NOT_BLIND")
        other = self.root / "other"
        other.mkdir()
        pair = make_pdf(other, "c.pdf", LINES["b.pdf"], model="some_other_model")
        with self.assertRaisesRegex(ValueError, "not an A0 output"):
            blind.register(Path("freeze.json"), self.root / "round2", [pair], non_blind=self.non_blind)

    def test_inputs_changed_after_selection_stop_the_round(self):
        self.prepare()
        a0 = self.pairs[0][1]
        a0.write_text(a0.read_text(encoding="utf-8").replace("Hello world", "Hello world!"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "changed since registration"):
            blind.score(Path("freeze.json"), self.round)


if __name__ == "__main__":
    unittest.main()

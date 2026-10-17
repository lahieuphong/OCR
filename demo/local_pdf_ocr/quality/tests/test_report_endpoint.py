"""Full no-model local report HTTP test with synthetic human-verified crops."""
from __future__ import annotations

import hashlib
import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from PIL import Image

from demo.local_pdf_ocr.backend.contract import CHECKPOINT_SHA256
from demo.local_pdf_ocr.quality.benchmark import metrics
from demo.local_pdf_ocr.quality.review_server import ReviewStore, make_handler


def write_jsonl(path, rows):
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )


class LocalReportEndpointTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        (self.folder / "crops").mkdir()
        manifest, labels = [], []
        for i in range(20):
            crop = self.folder / "crops" / f"crop{i:02}.png"
            Image.new("RGB", (85, 25), "white").save(crop)
            digest = hashlib.sha256(crop.read_bytes()).hexdigest()
            reference = "Số: 218/TB-VPCP" if i == 0 else f"Dòng số {i}"
            prediction = "Số: RU8/TB-VPCP" if i == 0 else reference
            manifest.append({
                "id": f"crop{i:02}", "document": "synthetic.pdf",
                "page": 1, "line_index": i + 1,
                "crop_path": f"crops/crop{i:02}.png",
                "crop_sha256": digest, "ocr_prediction": prediction,
            })
            labels.append({
                "id": f"crop{i:02}", "crop_sha256": digest,
                "reference": reference, "verified": True,
                **({"region_type": "printed_text", "region_reviewed": True} if i == 0 else {}),
            })
        write_jsonl(self.folder / "manifest.jsonl", manifest)
        write_jsonl(self.folder / "labels.jsonl", labels)
        old = {
            "status": "EXPERIMENT_ONLY_NO_DEPLOYMENT_APPROVAL",
            "blind_test_used": False,
            "baseline_reproduced_exactly": True,
            "samples_human_verified": 20,
            "frozen_checkpoint_sha256": CHECKPOINT_SHA256,
            "scores": {"baseline": metrics([
                (label["reference"], row["ocr_prediction"])
                for row, label in zip(manifest, labels)
            ])},
            "candidate_assessment": {
                "contrast_1p15": {"new_regression_line_ids": []},
                "unsharp_light": {"new_regression_line_ids": []},
                "autocontrast_1pct": {"new_regression_line_ids": []},
            },
        }
        (self.folder / "benchmark_report.json").write_text(
            json.dumps(old, ensure_ascii=False), encoding="utf-8",
        )
        detail = {
            "summary": {
                "no_blind_test": True, "selected_baseline_reproduced": True,
                "candidate_inference_performed": True,
            },
            "lines": [{
                "id": "crop00", "reference": "Số: 218/TB-VPCP",
                "baseline": "Số: RU8/TB-VPCP",
                "crop_sha256": manifest[0]["crop_sha256"],
                "variants": {
                    "contrast_1p15": {
                        "prediction": "Số: 218/TB-VPCP",
                        "char_errors": 0, "word_errors": 0,
                    },
                },
            }],
        }
        (self.folder / "error_analysis.json").write_text(
            json.dumps(detail, ensure_ascii=False), encoding="utf-8",
        )
        self.store = ReviewStore(self.folder)

    def test_local_report_preserves_labels_and_denies_stale_report(self):
        before = (self.folder / "labels.jsonl").read_bytes()
        summary = self.store.create_zone_report()
        self.assertEqual(summary["verified_lines"], 20)
        self.assertEqual(summary["region_reviewed_lines"], 1)
        self.assertEqual(summary["original_all_line_metrics"]["char_errors"], 2)
        self.assertEqual(summary["candidate_lines_with_local_improvement"], 1)
        self.assertTrue(summary["no_automatic_recognition_replacement"])
        self.assertFalse(summary["merge_approved"])
        self.assertEqual(before, (self.folder / "labels.jsonl").read_bytes())
        self.assertIn(b'"verified_lines": 20', self.store.report_asset("zone_audit.json"))
        self.assertIn("Số: RU8/TB-VPCP", self.store.report_asset("zone_audit.html").decode("utf-8"))
        self.store.save("crop01", "classify", region_type="stamp_artifact")
        with self.assertRaisesRegex(RuntimeError, "stale"):
            self.store.report_asset("zone_audit.json")
        new_summary = self.store.create_zone_report()
        self.assertEqual(new_summary["region_reviewed_lines"], 2)
        self.assertIn(b'"region_reviewed_lines": 2', self.store.report_asset("zone_audit.json"))

    def test_report_http_post_is_origin_token_protected(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.store))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            client = http.client.HTTPConnection("127.0.0.1", port, timeout=8)
            base_headers = {
                "Content-Type": "application/json",
                "Origin": f"http://127.0.0.1:{port}",
            }
            payload = json.dumps({"operation": "create"}).encode("utf-8")
            client.request("POST", "/api/zone-report", body=payload, headers=base_headers)
            response = client.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            base_headers["X-Review-Token"] = self.store.csrf_token
            client.request("POST", "/api/zone-report", body=payload, headers=base_headers)
            response = client.getresponse()
            self.assertEqual(response.status, 200)
            created = json.loads(response.read())
            self.assertEqual(created["summary"]["verified_lines"], 20)
            self.assertEqual(created["html_url"], "/reports/zone_audit.html")
            self.assertEqual(created["json_url"], "/reports/zone_audit.json")
            client.request("GET", "/reports/zone_audit.json")
            response = client.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())["summary"]["verified_lines"], 20)
            self.store.save("crop01", "classify", region_type="uncertain")
            client.request("GET", "/reports/zone_audit.html")
            response = client.getresponse()
            self.assertEqual(response.status, 409)
            response.read()
            client.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()

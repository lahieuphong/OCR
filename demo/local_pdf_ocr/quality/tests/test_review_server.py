"""Isolated localhost review editor tests; no real PDFs or models required."""
import hashlib
import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from PIL import Image
from demo.local_pdf_ocr.quality.review_server import ReviewStore, make_handler


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8")


class LabelEditorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "crops").mkdir()
        self.image = self.root / "crops" / "abc.png"
        Image.new("RGB", (160, 26), "white").save(self.image)
        self.digest = hashlib.sha256(self.image.read_bytes()).hexdigest()
        self.item = {
            "id": "abc", "document": "test.pdf", "page": 1, "line_index": 1,
            "ocr_prediction": "Nguyển", "crop_path": "crops/abc.png",
            "crop_sha256": self.digest,
        }
        write_jsonl(self.root / "manifest.jsonl", [self.item])
        write_jsonl(self.root / "labels.jsonl", [{
            "id": "abc", "crop_sha256": self.digest,
            "reference": None, "verified": False,
        }])
        self.store = ReviewStore(self.root)

    def test_update_is_atomic_preserves_hash_and_creates_backup(self):
        outcome = self.store.save("abc", "correct", "Nguyễn")
        self.assertEqual(outcome["verified_count"], 1)
        saved = json.loads((self.root / "labels.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(saved["reference"], "Nguyễn")
        self.assertEqual(saved["crop_sha256"], self.digest)
        backup = json.loads(
            (self.root / "labels.jsonl.before_ui.bak").read_text(encoding="utf-8")
        )
        self.assertFalse(backup["verified"])
        self.store.save("abc", "unverify")
        self.assertFalse(self.store.samples()["rows"][0]["verified"])

    def test_explicit_accept_keeps_exact_ocr_text(self):
        outcome = self.store.save("abc", "accept")
        self.assertEqual(outcome["reference"], "Nguyển")
        self.assertTrue(outcome["verified"])

    def test_reject_empty_multiline_and_unknown_id(self):
        for value in ("", " ", "a\nb"):
            with self.assertRaises(ValueError):
                self.store.save("abc", "correct", value)
        with self.assertRaises(ValueError):
            self.store.save("../labels.jsonl", "correct", "anything")
        self.assertFalse(json.loads((self.root / "labels.jsonl").read_text())["verified"])

    def test_external_file_edits_must_not_be_overwritten(self):
        write_jsonl(self.root / "labels.jsonl", [{
            "id": "abc", "crop_sha256": self.digest,
            "reference": "manual", "verified": True,
        }])
        with self.assertRaises(RuntimeError):
            self.store.save("abc", "accept")
        self.assertEqual(
            json.loads((self.root / "labels.jsonl").read_text())["reference"], "manual"
        )

    def test_crop_tampering_aborts_review(self):
        self.image.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "Crop"):
            ReviewStore(self.root)

    def test_http_review_roundtrip_requires_origin_and_csrf_token(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.store))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request("GET", "/api/samples")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            data = json.loads(response.read())
            self.assertEqual(len(data["rows"]), 1)

            payload = json.dumps({
                "id": "abc", "action": "correct", "reference": "Nguyễn"
            }).encode("utf-8")
            headers = {
                "Origin": f"http://127.0.0.1:{port}",
                "Content-Type": "application/json",
                "Content-Length": str(len(payload)),
            }
            connection.request("POST", "/api/review", body=payload, headers=headers)
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            response.read()

            headers["X-Review-Token"] = data["csrf_token"]
            connection.request("POST", "/api/review", body=payload, headers=headers)
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())["verified_count"], 1)

            connection.request("GET", "/crop/abc")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), self.image.read_bytes())
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()

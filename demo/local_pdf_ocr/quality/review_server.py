"""Local-only editor for OCR crop references.

Start from repo root:
 .venv-demo\Scripts\python.exe -m demo.local_pdf_ocr.quality.review_server --work-dir demo\local_pdf_ocr\quality_work\review_01
Then open http://127.0.0.1:8766/
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .benchmark import read_jsonl, sha256
from .zone_types import REVIEWABLE_REGION_TYPES


class ReviewStore:
    """Verify manifest/crop integrity and persist labels atomically."""

    def __init__(self, directory: Path):
        self.directory = directory.resolve(strict=True)
        self.labels_path = self.directory / "labels.jsonl"
        manifest = read_jsonl(self.directory / "manifest.jsonl")
        labels = read_jsonl(self.labels_path)
        if not manifest or len(manifest) != len(labels):
            raise ValueError("Manifest and labels must have the same nonempty row count")
        self.rows, self.labels, self.order = {}, {}, []
        for row in manifest:
            ident = row.get("id")
            if not isinstance(ident, str) or not ident or ident in self.rows:
                raise ValueError("Duplicate/empty manifest ID")
            self.rows[ident] = row
            self.order.append(ident)
        for label in labels:
            ident = label.get("id")
            if not isinstance(ident, str) or ident not in self.rows or ident in self.labels:
                raise ValueError("Duplicate/unknown label ID")
            if label.get("crop_sha256") != self.rows[ident].get("crop_sha256"):
                raise ValueError("Label crop SHA differs from manifest")
            self.labels[ident] = label
        if set(self.rows) != set(self.labels):
            raise ValueError("Some labels or manifest IDs are missing")
        self.crop_files = {}
        for ident, row in self.rows.items():
            target = (self.directory / row["crop_path"]).resolve()
            if (self.directory not in target.parents or target.suffix.lower() != ".png"
                    or not target.is_file() or sha256(target) != row["crop_sha256"]):
                raise ValueError(f"Crop missing/changed/outside review directory: {ident}")
            self.crop_files[ident] = target
        self.lock = threading.Lock()
        self.csrf_token = secrets.token_urlsafe(32)

    def samples(self) -> dict:
        with self.lock:
            return {
                "csrf_token": self.csrf_token,
                "rows": [{
                    "id": ident, "document": self.rows[ident].get("document", ""),
                    "page": self.rows[ident].get("page"),
                    "line_index": self.rows[ident].get("line_index"),
                    "ocr_prediction": self.rows[ident]["ocr_prediction"],
                    "header_split": self.rows[ident].get("header_split", False),
                    "layout_region": self.rows[ident].get("layout_region", ""),
                    "verified": self.labels[ident].get("verified") is True,
                    "reference": self.labels[ident].get("reference"),
                    "region_type": self.labels[ident].get("region_type"),
                    "region_reviewed": self.labels[ident].get("region_reviewed") is True,
                    "image_url": "/crop/" + ident,
                } for ident in self.order],
            }

    def save(self, ident: str, action: str, reference=None, region_type=None) -> dict:
        if ident not in self.rows:
            raise ValueError("Unknown crop ID")
        if action not in ("accept", "correct", "unverify", "classify"):
            raise ValueError("Unknown review action")
        if action == "classify":
            if region_type not in REVIEWABLE_REGION_TYPES:
                raise ValueError("Unknown region type")
        elif action == "accept":
            reference = self.rows[ident]["ocr_prediction"]
        elif action == "correct":
            if (not isinstance(reference, str) or not reference.strip()
                    or len(reference) > 5000 or "\r" in reference or "\n" in reference):
                raise ValueError("Enter one nonempty physical line, max 5000 characters")
        elif action == "unverify":
            reference = None
        if action not in ("unverify", "classify") and (
                not isinstance(reference, str) or not reference.strip()):
            raise ValueError("Cannot verify empty OCR text")
        with self.lock:
            current = read_jsonl(self.labels_path)
            disk = {row.get("id"): row for row in current}
            if len(disk) != len(self.order) or disk != self.labels:
                raise RuntimeError("labels.jsonl was edited outside the UI. Restart before saving.")
            previous = dict(self.labels[ident])
            if action == "classify":
                self.labels[ident] = {
                    **previous, "region_type": region_type, "region_reviewed": True,
                }
            else:
                self.labels[ident] = {
                    **previous, "reference": reference, "verified": action != "unverify",
                }
            temp = self.labels_path.with_name("labels.jsonl.tmp")
            try:
                backup = self.labels_path.with_name("labels.jsonl.before_ui.bak")
                if not backup.exists():
                    shutil.copy2(self.labels_path, backup)
                with temp.open("w", encoding="utf-8", newline="\n") as output:
                    for key in self.order:
                        output.write(json.dumps(self.labels[key], ensure_ascii=False, sort_keys=True) + "\n")
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temp, self.labels_path)
            except Exception:
                self.labels[ident] = previous
                temp.unlink(missing_ok=True)
                raise
            return {
                "id": ident,
                "reference": self.labels[ident].get("reference"),
                "verified": self.labels[ident].get("verified") is True,
                "region_type": self.labels[ident].get("region_type"),
                "region_reviewed": self.labels[ident].get("region_reviewed") is True,
                "verified_count": sum(item.get("verified") is True for item in self.labels.values()),
                "region_reviewed_count": sum(
                    item.get("region_reviewed") is True for item in self.labels.values()
                ),
                "total": len(self.rows),
            }


    def create_zone_report(self, *, min_verified: int = 20) -> dict:
        """Build offline QA outputs without rewriting verified labels or OCR predictions.

        A local file snapshot and in-memory review state must be identical.
        Outputs are atomically replaced only after full validation succeeds.
        """
        from .zone_audit import build_zone_audit, render_html

        with self.lock:
            actual = read_jsonl(self.labels_path)
            snapshot = {row.get("id"): row for row in actual}
            if len(snapshot) != len(self.order) or snapshot != self.labels:
                raise RuntimeError("Review labels changed outside the editor; restart server.")
            labels_sha = sha256(self.labels_path)
            report = build_zone_audit(self.directory, min_verified=min_verified)
            if (sha256(self.labels_path) != labels_sha
                    or report["summary"].get("source_labels_sha256") != labels_sha):
                raise RuntimeError("Labels changed during report generation. Retry after restarting.")
            files = (
                (self.directory / "zone_audit.json",
                 json.dumps(report, ensure_ascii=False, indent=2)),
                (self.directory / "zone_audit.html", render_html(report)),
            )
            # Validate both derived outputs before replacing either.
            for target, data in files:
                if not isinstance(data, str) or not data:
                    raise RuntimeError("Empty report rejected")
            for target, data in files:
                temporary = target.with_name(target.name + ".tmp")
                try:
                    with temporary.open("w", encoding="utf-8", newline="\n") as output:
                        output.write(data)
                        output.flush()
                        os.fsync(output.fileno())
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
            return report["summary"]

    def report_asset(self, name: str) -> bytes:
        if name not in ("zone_audit.html", "zone_audit.json"):
            raise ValueError("Unknown report file")
        with self.lock:
            metadata = self.directory / "zone_audit.json"
            target = self.directory / name
            if not metadata.is_file() or not target.is_file():
                raise ValueError("No report exists. Create it in the review page.")
            report = json.loads(metadata.read_text(encoding="utf-8"))
            if report.get("summary", {}).get("source_labels_sha256") != sha256(self.labels_path):
                raise RuntimeError("Report is stale after label edits; create a new report.")
            return target.read_bytes()


def make_handler(store: ReviewStore):
    class Handler(BaseHTTPRequestHandler):
        server_version = "VietDocReviewLocal/1.0"

        def _send(self, code, value: bytes, mime):
            self.send_response(code)
            for header, data in (
                ("Content-Type", mime), ("Content-Length", str(len(value))),
                ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
                ("X-Frame-Options", "DENY"),
                ("Content-Security-Policy",
                 "default-src 'none'; script-src 'self'; style-src 'self'; "
                 "img-src 'self'; connect-src 'self'; base-uri 'none'; "
                 "form-action 'none'; frame-ancestors 'none'"),
            ):
                self.send_header(header, data)
            self.end_headers()
            self.wfile.write(value)

        def _json(self, code, value):
            self._send(code, json.dumps(value, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _localhost(self):
            return self.headers.get("Host") == f"127.0.0.1:{self.server.server_address[1]}"

        def do_GET(self):
            if not self._localhost():
                return self._json(403, {"error": "Only localhost is allowed"})
            path = urlsplit(self.path).path
            if path == "/api/samples":
                return self._json(200, store.samples())
            if path in ("/reports/zone_audit.html", "/reports/zone_audit.json"):
                name = path.rsplit("/", 1)[-1]
                try:
                    payload = store.report_asset(name)
                except ValueError as exc:
                    return self._json(404, {"error": str(exc)})
                except RuntimeError as exc:
                    return self._json(409, {"error": str(exc)})
                mime = ("text/html; charset=utf-8" if name.endswith(".html")
                        else "application/json; charset=utf-8")
                return self._send(200, payload, mime)
            if path in ("/", "/review_ui.html", "/review_ui.css", "/review_ui.js"):
                name = "review_ui.html" if path == "/" else path.lstrip("/")
                asset = Path(__file__).parent / name
                mime = {
                    ".html": "text/html; charset=utf-8",
                    ".css": "text/css; charset=utf-8",
                    ".js": "text/javascript; charset=utf-8",
                }[asset.suffix]
                return self._send(200, asset.read_bytes(), mime)
            if path.startswith("/crop/"):
                ident = unquote(path[len("/crop/"):])
                target = store.crop_files.get(ident)
                if target is None:
                    return self._json(404, {"error": "Unknown crop"})
                if sha256(target) != store.rows[ident]["crop_sha256"]:
                    return self._json(409, {"error": "Crop changed. Stop reviewing."})
                return self._send(200, target.read_bytes(), "image/png")
            return self._json(404, {"error": "Not found"})

        def do_POST(self):
            if (not self._localhost()
                    or self.headers.get("Origin") != f"http://127.0.0.1:{self.server.server_address[1]}"
                    or self.headers.get("X-Review-Token") != store.csrf_token):
                return self._json(403, {"error": "Invalid local review origin/token"})
            resource = urlsplit(self.path).path
            if resource not in ("/api/review", "/api/zone-report"):
                return self._json(404, {"error": "Not found"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 16384:
                    raise ValueError("Invalid request size")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("Expected JSON object")
                if resource == "/api/zone-report":
                    if data.get("operation") != "create" or set(data) != {"operation"}:
                        raise ValueError("Report creation requires explicit operation=create")
                    return self._json(200, {
                        "summary": store.create_zone_report(),
                        "html_url": "/reports/zone_audit.html",
                        "json_url": "/reports/zone_audit.json",
                    })
                return self._json(200, store.save(
                    data.get("id"), data.get("action"), data.get("reference"),
                    data.get("region_type")))
            except ValueError as exc:
                return self._json(400, {"error": str(exc)})
            except RuntimeError as exc:
                return self._json(409, {"error": str(exc)})

    return Handler


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args(argv)
    if not 1025 <= args.port <= 65535:
        parser.error("Choose an unprivileged TCP port (1025-65535)")
    store = ReviewStore(args.work_dir)
    with ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(store)) as server:
        print(f"Open http://127.0.0.1:{args.port}/ to verify {len(store.rows)} crops")
        print("All labels are saved locally; Ctrl+C stops the editor.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nReview editor stopped; saved labels remain intact.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

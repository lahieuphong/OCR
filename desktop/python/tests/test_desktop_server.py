"""Desktop server: the request guard on its own, then the real server process with no model and no detector.

Synthetic inputs only (an in-memory PDF and PNG); no model inference, no download, no real document.
Run from the repository root: <python> -m unittest discover -s desktop/python/tests -p "test_*.py"
"""
import asyncio
import io
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SERVER = REPO / "desktop" / "python" / "vietdoc_desktop_server.py"
LOCK = REPO / "desktop" / "model_lock.json"
sys.path.insert(0, str(SERVER.parent))
import vietdoc_desktop_server as desktop  # noqa: E402


def call(guard, method="GET", path="/", headers=(), client="127.0.0.1"):
    """One request through the ASGI guard; returns (status, response headers)."""
    sent, inner_called = [], []

    async def inner(scope, receive, send):
        inner_called.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"ok"})

    guard.app = inner
    scope = {"type": "http", "method": method, "path": path, "client": (client, 50000),
             "headers": [(k.encode(), v.encode()) for k, v in headers]}

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        sent.append(message)

    asyncio.run(guard(scope, receive, send))
    start = sent[0]
    return start["status"], {k.decode(): v.decode() for k, v in start["headers"]}, bool(inner_called)


class Guard(unittest.TestCase):
    def setUp(self):
        self.token = secrets.token_hex(32)
        self.guard = desktop.DesktopGuard(None, self.token, 50123)
        self.ok = [("host", "127.0.0.1:50123"), ("x-vietdoc-token", self.token)]

    def test_a_request_needs_token_host_origin_client_and_method(self):
        self.assertEqual(call(self.guard, headers=self.ok)[0], 200)
        cases = {
            "no token": [("host", "127.0.0.1:50123")],
            "wrong token": [("host", "127.0.0.1:50123"), ("x-vietdoc-token", "0" * 64)],
            "localhost name": [("host", "localhost:50123"), ("x-vietdoc-token", self.token)],
            "other port": [("host", "127.0.0.1:50124"), ("x-vietdoc-token", self.token)],
            "foreign origin": self.ok + [("origin", "http://evil.example")],
            "null origin": self.ok + [("origin", "null")],
        }
        for name, headers in cases.items():
            with self.subTest(name):
                status, _, reached = call(self.guard, headers=headers)
                self.assertEqual((status, reached), (403, False))
        self.assertEqual(call(self.guard, headers=self.ok + [("origin", "http://127.0.0.1:50123")])[0], 200)
        self.assertEqual(call(self.guard, headers=self.ok, client="192.168.1.20")[0], 403)
        self.assertEqual(call(self.guard, method="PUT", headers=self.ok)[0], 403)

    def test_security_headers_and_no_store_on_api(self):
        _, headers, _ = call(self.guard, path="/api/health", headers=self.ok)
        self.assertIn("frame-ancestors 'none'", headers["content-security-policy"])
        self.assertEqual((headers["x-content-type-options"], headers["cache-control"]), ("nosniff", "no-store"))
        _, headers, _ = call(self.guard, path="/assets/app.js", headers=self.ok)
        self.assertNotIn("cache-control", headers)

    def test_detector_check_reports_missing_and_changed_files(self):
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as home:
            self.assertEqual(len(desktop.check_detector(Path(home), lock)["problems"]), 3)
            folder = Path(home) / "official_models" / lock["detector"]["model_name"]
            folder.mkdir(parents=True)
            for name in lock["detector"]["files"]:
                (folder / name).write_bytes(b"not the frozen detector")
            result = desktop.check_detector(Path(home), lock)
            self.assertFalse(result["ok"])
            self.assertTrue(all("SHA-256" in p for p in result["problems"]))


def synthetic_pdf() -> bytes:
    import pymupdf

    doc = pymupdf.open()
    doc.new_page(width=300, height=200).insert_text((20, 40), "Tai lieu tong hop de kiem thu", fontsize=11)
    return doc.tobytes()


def synthetic_png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (64, 32), "white").save(buffer, "PNG")
    return buffer.getvalue()


def multipart(fields: dict, file_name: str, content: bytes, content_type: str):
    boundary = uuid.uuid4().hex
    parts = []
    for key, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file_name}"\r\n'
                 f"Content-Type: {content_type}\r\n\r\n".encode() + content + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


class RunningServer(unittest.TestCase):
    """The real server process: models absent (as in a fresh worktree) and an empty PaddleX home."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        dist = root / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<!doctype html><title>VietDoc OCR</title><div id=root></div>", encoding="utf-8")
        cls.paddlex_home = root / "paddlex_home"
        cls.paddlex_home.mkdir()
        cls.token = secrets.token_hex(32)
        cls.proc = subprocess.Popen(
            [sys.executable, "-I", "-B", "-X", "utf8", str(SERVER), "--repo-root", str(REPO), "--frontend-dist", str(dist),
             "--model-lock", str(LOCK), "--paddlex-home", str(cls.paddlex_home)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        cls.proc.stdin.write(cls.token + "\n")
        cls.proc.stdin.flush()
        deadline, cls.port = time.time() + 120, None
        while time.time() < deadline:
            line = cls.proc.stdout.readline()
            if not line:
                break
            if line.startswith("VIETDOC_READY "):
                cls.ready = json.loads(line.split(" ", 1)[1])
                cls.port = cls.ready["port"]
                break
        if cls.port is None:
            cls.proc.kill()
            raise RuntimeError("desktop server did not become ready")

    @classmethod
    def tearDownClass(cls):
        if cls.proc.poll() is None:
            cls.proc.kill()
        cls.proc.wait(timeout=10)
        cls.proc.stdin.close()
        cls.proc.stdout.close()
        cls.tmp.cleanup()

    def request(self, path, method="GET", body=None, content_type=None, token=True, host=None):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=body, method=method)
        if token:
            request.add_header("X-VietDoc-Token", self.token)
        if content_type:
            request.add_header("Content-Type", content_type)
        if host:
            request.add_header("Host", host)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as error:
            return error.code, error.read(), dict(error.headers)

    def test_1_only_loopback_and_only_with_the_token(self):
        self.assertFalse(self.ready["ocr_allowed"])
        self.assertEqual(self.request("/", token=False)[0], 403)
        self.assertEqual(self.request("/api/health", token=False)[0], 403)
        self.assertEqual(self.request("/api/health", host="localhost:%d" % self.port)[0], 403)
        status, body, headers = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn(b"VietDoc OCR", body)
        self.assertIn("default-src 'self'", headers["content-security-policy"])
        # The listening socket is bound to 127.0.0.1 only.
        with self.assertRaises(OSError):
            import socket
            other = [a for a in socket.gethostbyname_ex(socket.gethostname())[2] if not a.startswith("127.")]
            if not other:
                raise OSError("no non-loopback address to test")
            socket.create_connection((other[0], self.port), timeout=2).close()

    def test_2_status_reports_blocked_models_without_downloading(self):
        status, body, headers = self.request("/__desktop__/status")
        data = json.loads(body)
        self.assertEqual((status, headers.get("cache-control")), (200, "no-store"))
        self.assertFalse(data["ocr_allowed"])
        self.assertFalse(data["recognizer"]["ok"])
        self.assertEqual(len(data["detector"]["problems"]), 3)
        self.assertEqual(data["limits"], {"max_upload_bytes": 15 * 1024 * 1024, "max_pdf_pages": 6, "max_image_pixels": 12_000_000})
        self.assertEqual(data["model_downloads"], "disabled")
        self.assertEqual(json.loads(self.request("/api/health")[1])["state"], "missing_model_files")

    def test_3_ocr_is_refused_but_native_text_works(self):
        body, ctype = multipart({"mode": "vietocr_ocr"}, "anh.png", synthetic_png(), "image/png")
        status, payload, _ = self.request("/api/ocr", "POST", body, ctype)
        self.assertEqual(status, 503)
        self.assertIn("chặn OCR", json.loads(payload)["detail"])
        self.assertEqual(list((self.paddlex_home).rglob("*")), [])  # nothing was downloaded
        body, ctype = multipart({"mode": "native_text"}, "tong_hop.pdf", synthetic_pdf(), "application/pdf")
        status, payload, _ = self.request("/api/ocr", "POST", body, ctype)
        self.assertEqual(status, 200)
        result = json.loads(payload)
        self.assertEqual(result["method"], "native_text")
        self.assertIn("Tai lieu tong hop", result["text"])
        too_big = b"%PDF-" + b"0" * (15 * 1024 * 1024)
        body, ctype = multipart({"mode": "native_text"}, "lon.pdf", too_big, "application/pdf")
        self.assertEqual(self.request("/api/ocr", "POST", body, ctype)[0], 400)  # the existing 15 MB limit

    def test_4_shutdown_stops_the_process(self):
        self.assertEqual(self.request("/__desktop__/shutdown", "POST", b"")[0], 200)
        self.assertEqual(self.proc.wait(timeout=20), 0)


class ParentGone(unittest.TestCase):
    def test_closing_stdin_stops_the_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp) / "dist"
            dist.mkdir()
            (dist / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
            proc = subprocess.Popen([sys.executable, "-I", "-B", "-X", "utf8", str(SERVER), "--repo-root", str(REPO), "--frontend-dist",
                                     str(dist), "--model-lock", str(LOCK), "--paddlex-home", tmp],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            proc.stdin.write(secrets.token_hex(32) + "\n")
            proc.stdin.flush()
            while True:
                line = proc.stdout.readline()
                if not line or line.startswith("VIETDOC_READY"):
                    break
            self.assertTrue(line.startswith("VIETDOC_READY"))
            proc.stdin.close()
            self.assertEqual(proc.wait(timeout=20), 0)
            proc.stdout.close()

    def test_a_missing_token_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            done = subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", str(SERVER), "--repo-root", str(REPO), "--frontend-dist", tmp,
                                   "--model-lock", str(LOCK)], input="\n", capture_output=True, text=True, timeout=60)
            self.assertEqual(done.returncode, 2)
            self.assertIn("token", done.stdout)


class WatchedPipe(unittest.TestCase):
    """While the watchdog waits on the parent's pipe, native imports and child processes must not block.

    Regression: with the watchdog blocked reading fd 0, `import numpy` (OpenBLAS) never returned on
    Windows, so the first real OCR request (PaddleX imports numpy) hung until Electron closed the pipe.
    """

    CHILD = (
        "import subprocess, sys, threading, time\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "import vietdoc_desktop_server as desktop\n"
        "sys.stdin.readline()\n"
        "pipe = desktop.detach_stdin()\n"
        "threading.Thread(target=lambda: pipe.read(4096), daemon=True).start()\n"
        "time.sleep(0.3)\n"
        "import numpy\n"
        "print('numpy imported', flush=True)\n"
        "out = subprocess.run([sys.executable, '-I', '-c', 'import sys; print(repr(sys.stdin.read()))'],\n"
        "                     capture_output=True, text=True, timeout=20).stdout.strip()\n"
        "print('grandchild stdin', out, flush=True)\n"
    )

    def test_native_import_and_children_do_not_wait_for_the_parent_pipe(self):
        proc = subprocess.Popen([sys.executable, "-I", "-B", "-c", self.CHILD, str(SERVER.parent)],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        lines = []
        reader = threading.Thread(target=lambda: lines.extend(line.strip() for line in proc.stdout), daemon=True)
        reader.start()
        try:
            proc.stdin.write("token\n")
            proc.stdin.flush()  # the pipe stays open while we wait, as Electron keeps it
            deadline = time.time() + 60
            while time.time() < deadline and len(lines) < 2:
                time.sleep(0.1)
            self.assertEqual(lines[:2], ["numpy imported", "grandchild stdin ''"],
                             "a native import or a child process waited for the parent's pipe")
        finally:
            proc.stdin.close()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            reader.join(timeout=5)
            proc.stdout.close()


if __name__ == "__main__":
    unittest.main()

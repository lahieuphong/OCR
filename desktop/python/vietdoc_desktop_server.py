"""VietDoc OCR desktop server: the existing FastAPI app, served to the Electron window only.

Started by the Electron main process (desktop/electron/lib/backend.js), never by hand in normal use:

  <python> -I -B desktop/python/vietdoc_desktop_server.py --repo-root <worktree> --frontend-dist <dist>
           --model-lock desktop/model_lock.json [--paddlex-home <dir>]      (token on the first stdin line)

What it adds around demo/local_pdf_ocr/backend/app.py, whose recognition code, limits and model
checks stay untouched:
- binds 127.0.0.1 only, on a free port, and prints one line ``VIETDOC_READY {"port": N, "pid": P}``;
- every request must carry the per-launch token (X-VietDoc-Token), come from 127.0.0.1, name the
  host exactly 127.0.0.1:N and, when it has an Origin, that same origin: a request merely coming
  from localhost is not trusted;
- serves the built React frontend from that same origin, so the UI calls /api/... unchanged;
- OCR is allowed only after contract.verify_frozen_onnx (unchanged, SHA-256 pinned in code) and
  the detector files match model_lock.json; until then the engine is never created and PaddleX
  model hosters are disabled, so no model can be downloaded;
- GET /__desktop__/status reports backend and model state; POST /__desktop__/shutdown stops it,
  and so does the parent closing stdin (Electron gone).
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import platform
import socket
import sys
import threading
import time
from importlib import metadata
from pathlib import Path

SECURITY_HEADERS = [
    (b"content-security-policy",
     b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; "
     b"font-src 'self' data:; connect-src 'self'; frame-src 'self' blob:; object-src 'none'; base-uri 'none'; "
     b"form-action 'self'; frame-ancestors 'none'"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
]
ALLOWED_METHODS = {"GET", "HEAD", "POST"}
DESKTOP_PREFIX = "/__desktop__/"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as reader:
        for block in iter(lambda: reader.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check_detector(paddlex_home: Path, lock: dict) -> dict:
    """The detector PaddleX will load (<home>/official_models/<model>) against the pinned hashes."""
    folder = paddlex_home / "official_models" / lock["detector"]["model_name"]
    problems = []
    for name, expected in lock["detector"]["files"].items():
        path = folder / name
        if not path.is_file():
            problems.append(f"thiếu {name}")
        elif sha256_file(path) != expected:
            problems.append(f"{name} khác SHA-256 đã khóa")
    return {"ok": not problems, "dir": str(folder), "problems": problems}


def check_recognizer() -> dict:
    from demo.local_pdf_ocr.backend import contract

    try:
        contract.verify_frozen_onnx(require_weights=True)
        return {"ok": True, "dir": str(contract.MODEL_DIR), "problems": []}
    except contract.DemoConfigurationError as error:
        return {"ok": False, "dir": str(contract.MODEL_DIR), "problems": [str(error)]}


def disable_model_downloads() -> None:
    """PaddleX downloads a missing official model; with no hoster it can only fail."""
    from paddlex.inference.utils import official_models

    official_models._ModelManager._build_hosters = lambda self: []
    official_models.official_models._hosters = []


class DesktopGuard:
    """ASGI wrapper: token, client, host and origin checks on every request; security headers on every response."""

    def __init__(self, app, token: str, port: int):
        self.app, self.token, self.port = app, token.encode("ascii"), port
        self.host = f"127.0.0.1:{port}".encode("ascii")
        self.origin = f"http://127.0.0.1:{port}".encode("ascii")
        self.rejected = 0

    def allowed(self, scope) -> bool:
        headers = {}
        for key, value in scope.get("headers", []):
            headers.setdefault(key.lower(), value)
        client = (scope.get("client") or ("", 0))[0]
        origin = headers.get(b"origin")
        return (client == "127.0.0.1" and scope.get("method") in ALLOWED_METHODS
                and headers.get(b"host") == self.host and (origin is None or origin == self.origin)
                and hmac.compare_digest(headers.get(b"x-vietdoc-token", b""), self.token))

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.app(scope, receive, send)
        if scope["type"] != "http" or not self.allowed(scope):
            self.rejected += 1
            if scope["type"] == "http":
                await send({"type": "http.response.start", "status": 403,
                            "headers": [(b"content-type", b"text/plain; charset=utf-8"), *SECURITY_HEADERS]})
                await send({"type": "http.response.body", "body": b"Forbidden"})
            return None
        no_store = scope["path"].startswith(("/api/", DESKTOP_PREFIX))

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                names = {k.lower() for k, _ in message.get("headers", [])}
                extra = [h for h in SECURITY_HEADERS if h[0] not in names]
                if no_store and b"cache-control" not in names:
                    extra.append((b"cache-control", b"no-store"))
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        return await self.app(scope, receive, send_with_headers)


def build(repo_root: Path, frontend_dist: Path, lock: dict, paddlex_home: Path, token: str, port: int):
    """The wrapped ASGI app and its mutable state; imports the backend from repo_root.

    A frozen (packaged) server carries the backend inside its bundle: it never adds a folder from the
    command line to sys.path, so no module can be picked up from outside the bundle.
    """
    if not getattr(sys, "frozen", False):
        sys.path.insert(0, str(repo_root))
    os.environ["PADDLE_PDX_CACHE_HOME"] = str(paddlex_home)  # PaddleX reads it at import: same dir as checked
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    from fastapi import HTTPException
    from starlette.staticfiles import StaticFiles

    from demo.local_pdf_ocr.backend import app as backend_app
    from demo.local_pdf_ocr.backend import contract

    state = {"server": None, "started_at": time.time(), "port": port, "pid": os.getpid(),
             "recognizer": check_recognizer(), "detector": check_detector(paddlex_home, lock)}
    state["ocr_allowed"] = state["recognizer"]["ok"] and state["detector"]["ok"]
    original_get_engine = backend_app.get_engine

    def guarded_get_engine():
        # Re-check right before the engine exists: a detector removed since start must not be downloaded.
        state["detector"] = check_detector(paddlex_home, lock)
        state["ocr_allowed"] = state["recognizer"]["ok"] and state["detector"]["ok"]
        if not state["ocr_allowed"]:
            reasons = state["recognizer"]["problems"] + state["detector"]["problems"]
            raise contract.DemoConfigurationError("Bản desktop chặn OCR: " + "; ".join(reasons))
        disable_model_downloads()
        return original_get_engine()

    backend_app.get_engine = guarded_get_engine
    app = backend_app.app

    def versions() -> dict:
        found = {"python": platform.python_version()}
        for name in ("fastapi", "uvicorn", "onnxruntime", "paddlepaddle", "paddlex", "pymupdf"):
            try:
                found[name] = metadata.version(name)
            except metadata.PackageNotFoundError:
                found[name] = None
        return found

    def status():
        return {"backend": "running", "pid": state["pid"], "port": state["port"],
                "uptime_s": round(time.time() - state["started_at"], 1), "ocr_allowed": state["ocr_allowed"],
                "native_text_allowed": True, "recognizer": state["recognizer"], "detector": state["detector"],
                "limits": {"max_upload_bytes": contract.MAX_UPLOAD_BYTES, "max_pdf_pages": contract.MAX_PDF_PAGES,
                           "max_image_pixels": contract.MAX_IMAGE_PIXELS},
                "frontend_dist": str(frontend_dist), "versions": versions(), "model_downloads": "disabled",
                "runtime": {"frozen": bool(getattr(sys, "frozen", False)), "utf8_mode": bool(sys.flags.utf8_mode)}}

    def shutdown():
        server = state["server"]
        if server is None:
            raise HTTPException(status_code=503, detail="server not started")
        server.should_exit = True
        return {"stopping": True}

    app.add_api_route(DESKTOP_PREFIX + "status", status, methods=["GET"])
    app.add_api_route(DESKTOP_PREFIX + "shutdown", shutdown, methods=["POST"])
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
    return DesktopGuard(app, token, port), state


def detach_stdin():
    """Hand the parent's pipe to the watchdog alone; fd 0 (and every child process) gets NUL.

    On Windows a thread blocked reading fd 0 holds the C runtime lock of fd 0, and native libraries
    can touch fd 0 while they load: importing numpy (OpenBLAS) froze the first real OCR request,
    which imports PaddleX and numpy. The watchdog therefore reads a private, non-inheritable
    duplicate of the pipe, and fd 0 plus the standard input handle point to NUL, so children no
    longer inherit the parent's pipe either. Returns an unbuffered binary reader of that pipe.
    """
    private = os.dup(0)  # non-inheritable
    devnull = os.open(os.devnull, os.O_RDONLY)
    try:
        os.dup2(devnull, 0)
    finally:
        os.close(devnull)
    if os.name == "nt":
        import ctypes
        import msvcrt

        ctypes.windll.kernel32.SetStdHandle(-10, msvcrt.get_osfhandle(0))  # STD_INPUT_HANDLE -> NUL
    return os.fdopen(private, "rb", buffering=0)


def bind_loopback() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows: no other process may bind the same port
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(64)
    return sock


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--frontend-dist", type=Path, required=True)
    parser.add_argument("--model-lock", type=Path, required=True)
    parser.add_argument("--paddlex-home", type=Path, default=Path.home() / ".paddlex")
    args = parser.parse_args(argv)
    token = sys.stdin.readline().strip()
    if len(token) < 32 or any(c not in "0123456789abcdef" for c in token):
        print("VIETDOC_ERROR missing or malformed token on stdin", flush=True)
        return 2
    if not (args.frontend_dist / "index.html").is_file():
        print(f"VIETDOC_ERROR frontend build not found: {args.frontend_dist}", flush=True)
        return 2
    parent_pipe = detach_stdin()  # before any native library is loaded
    import uvicorn

    lock = json.loads(args.model_lock.read_text(encoding="utf-8"))
    sock = bind_loopback()
    port = sock.getsockname()[1]
    guarded, state = build(args.repo_root.resolve(), args.frontend_dist.resolve(), lock, args.paddlex_home, token, port)
    server = uvicorn.Server(uvicorn.Config(guarded, log_level="info", access_log=False, lifespan="on"))
    state["server"] = server

    def announce():
        while not server.started and not server.should_exit:
            time.sleep(0.05)
        if server.started:
            print("VIETDOC_READY " + json.dumps({"port": port, "pid": os.getpid(), "ocr_allowed": state["ocr_allowed"]}),
                  flush=True)

    def watch_parent():
        with parent_pipe:
            while parent_pipe.read(4096):  # b"" once the parent closes the pipe or dies
                pass
        server.should_exit = True

    threading.Thread(target=announce, daemon=True).start()
    threading.Thread(target=watch_parent, daemon=True).start()
    server.run(sockets=[sock])
    print("VIETDOC_STOPPED", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""The browser front end of ``annotate.py``: one page served on localhost.

Standard library only. The server listens on 127.0.0.1, so the crops never
leave this machine, and it accepts changes only from the page it served: a
request must carry the token embedded in that page and name this host.
"""

from __future__ import annotations

import json
import secrets
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import quote, unquote

import bakeoff_common as bakeoff
from annotation_store import SKIP_REASONS, ActionError, AnnotationStore

PAGE = Path(__file__).resolve().parent / "annotation_page.html"
HOST = "127.0.0.1"
MAX_BODY_BYTES = 64 * 1024


class AnnotationApp:
    """What the page can ask for, independent of HTTP."""

    def __init__(self, store: AnnotationStore, crop_file: Callable[[dict], Path]) -> None:
        self.store, self.crop_file = store, crop_file
        self.lock = threading.Lock()
        self.token = secrets.token_urlsafe(24)

    def state(self) -> dict:
        row = self.store.current()
        item = None
        if row is not None:
            item = {
                "id": row["id"],
                "document": row["document"],
                "page": row["page"],
                "ppocr": row["ppocr_prediction"],
                "vietocr": row["vietocr_prediction"],
                "image": f"/crop/{quote(row['id'], safe='')}",
                # Only set when a verified row is reopened on purpose.
                "ground_truth": row["ground_truth"],
            }
        return {
            "item": item,
            "done": item is None,
            "stop_reason": self.store.stop_reason() if item is None else "",
            "progress": self.store.progress(),
            "annotator": self.store.annotator,
            "skip_reasons": SKIP_REASONS,
        }

    def act(self, request: dict) -> dict:
        """Apply one action of the annotator and return the new state."""
        action, row_id = request.get("action"), str(request.get("id", ""))
        with self.lock:
            if action == "accept_ppocr":
                self.store.accept(row_id, bakeoff.PPOCR)
            elif action == "accept_vietocr":
                self.store.accept(row_id, bakeoff.VIETOCR)
            elif action == "enter":
                self.store.enter(row_id, str(request.get("text", "")))
            elif action == "skip":
                self.store.skip(row_id, str(request.get("reason", "")))
            elif action == "undo":
                self.store.undo()
            elif action == "quit":
                self.store.stop()
            else:
                raise ActionError(f"Unknown action {action!r}.")
            return self.state()

    def crop(self, row_id: str) -> bytes:
        row = self.store.by_id.get(row_id)
        if row is None:
            raise KeyError(row_id)
        return self.crop_file(row).read_bytes()


def make_handler(app: AnnotationApp, allowed_hosts: set[str], finish: Callable[[], None]):
    class Handler(BaseHTTPRequestHandler):
        server_version = "AnnotationServer"

        def log_message(self, *arguments) -> None:  # keep the terminal quiet
            pass

        def reply(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def reply_json(self, data: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.reply(status, body, "application/json; charset=utf-8")

        def host_is_local(self) -> bool:
            # A page on another site cannot reach this server under its own name.
            if self.headers.get("Host") in allowed_hosts:
                return True
            self.reply_json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
            return False

        def do_GET(self) -> None:
            if not self.host_is_local():
                return
            if self.path == "/":
                page = PAGE.read_text(encoding="utf-8").replace("__TOKEN__", app.token)
                self.reply(HTTPStatus.OK, page.encode("utf-8"), "text/html; charset=utf-8")
            elif self.path == "/api/state":
                with app.lock:
                    self.reply_json(app.state())
            elif self.path.startswith("/crop/"):
                try:
                    self.reply(HTTPStatus.OK, app.crop(unquote(self.path[len("/crop/"):])), "image/png")
                except (KeyError, SystemExit) as error:
                    # Unknown id, or a crop that is no longer the exported file.
                    self.reply_json({"error": str(error)}, HTTPStatus.NOT_FOUND)
            else:
                self.reply_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            if not self.host_is_local():
                return
            if self.path != "/api/action" or self.headers.get("X-Annotation-Token") != app.token:
                self.reply_json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
                return
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= MAX_BODY_BYTES:
                self.reply_json({"error": "bad request"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                state = app.act(json.loads(self.rfile.read(length)))
            except (ActionError, json.JSONDecodeError) as error:
                with app.lock:
                    self.reply_json({"error": str(error), **app.state()}, HTTPStatus.CONFLICT)
                return
            self.reply_json(state)
            if state["done"]:
                finish()

    return Handler


def announce(message: str) -> None:
    print(message, flush=True)  # visible at once even when output goes to a file


def serve(
    app: AnnotationApp, port: int, open_browser: bool, say: Callable[[str], None] = announce
) -> None:
    """Serve the page until the session is over (target reached or the annotator quits)."""
    over = threading.Event()
    allowed_hosts: set[str] = set()
    server = ThreadingHTTPServer((HOST, port), make_handler(app, allowed_hosts, over.set))
    port = server.server_address[1]  # the real one when 0 was asked for
    allowed_hosts.update({f"{HOST}:{port}", f"localhost:{port}"})
    url = f"http://{HOST}:{port}/"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    say(f"Annotation page: {url}")
    say("Leave this running while you annotate. Ctrl-C here also saves and stops.")
    if open_browser:
        webbrowser.open(url)
    try:
        over.wait()
        # Let the page receive the reply that ended the session.
        threading.Event().wait(1.0)
    except KeyboardInterrupt:
        say("")
    finally:
        server.shutdown()
        server.server_close()

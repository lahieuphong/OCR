"""Real OCR through a packaged VietDoc OCR (installed Setup or extracted Portable), compared with the source.

Starts the app's own backend the way the Electron shell does (packaged executable, resources folder as working
directory, token on stdin, minimal environment, the bundled models: resources/models and resources/paddlex), sends
each document with its mode to /api/ocr and saves every response. With --dev-python it starts the development server
of the checkout instead (the reference). --compare <dir> compares the responses with an earlier run of this tool.

Usage:
  python packaging/windows/check_packaged_ocr.py --app "<folder holding VietDoc OCR.exe>" --out <dir>
         --doc <file>=<mode> [--doc ...] [--compare <reference dir>]
  python packaging/windows/check_packaged_ocr.py --dev-python <python.exe> --model-root <dir> --paddlex-home <dir>
         --out <dir> --doc ...

Modes: native_text, vietocr_ocr, hybrid_h1, metadata_fast. Timing fields are left out of the comparison; everything
else in a response must be identical. Documents never leave this machine; outputs are written only under --out.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "packaging" / "ci"))
from probe_backend import backend_command, cleanup, probe_environment, read_line, req  # noqa: E402

MODES = {"native_text", "vietocr_ocr", "hybrid_h1", "metadata_fast"}
TIMING_KEY = ("elapsed", "_ms", "seconds", "duration", "timing")


def strip_timing(value):
    if isinstance(value, dict):
        return {k: strip_timing(v) for k, v in value.items() if not any(t in k.lower() for t in TIMING_KEY)}
    if isinstance(value, list):
        return [strip_timing(v) for v in value]
    return value


def differences(left, right, path="$", limit=20) -> list[str]:
    found: list[str] = []

    def walk(a, b, where):
        if len(found) >= limit:
            return
        numbers = (int, float)
        if isinstance(a, numbers) and isinstance(b, numbers) and not isinstance(a, bool) and not isinstance(b, bool):
            if a != b:   # by value: a browser export writes 356.0 as 356
                found.append(f"{where}: {a!r} != {b!r}")
            return
        if type(a) is not type(b):
            found.append(f"{where}: {type(a).__name__} != {type(b).__name__}")
        elif isinstance(a, dict):
            for key in sorted(a.keys() | b.keys()):
                if key not in a or key not in b:
                    found.append(f"{where}.{key}: only in {'reference' if key in b else 'this run'}")
                else:
                    walk(a[key], b[key], f"{where}.{key}")
        elif isinstance(a, list):
            if len(a) != len(b):
                found.append(f"{where}: {len(a)} items != {len(b)}")
            for i, (x, y) in enumerate(zip(a, b)):
                walk(x, y, f"{where}[{i}]")
        elif a != b:
            found.append(f"{where}: {str(a)[:80]!r} != {str(b)[:80]!r}")

    walk(left, right, path)
    return found


def server_command(args) -> tuple[list[str], dict, str]:
    if args.app:
        resources = str(Path(args.app, "resources"))
        exe = backend_command(resources)
        env = probe_environment(exe)
        env["VIETDOC_MODEL_ROOT"] = str(Path(resources, "models"))   # config.js: the bundled folder, absolute
        command = [exe, "--repo-root", resources, "--frontend-dist", str(Path(resources, "frontend")),
                   "--model-lock", str(Path(resources, "model_lock.json")), "--paddlex-home", str(Path(resources, "paddlex"))]
        return command, env, resources
    env = probe_environment(args.dev_python)
    env["VIETDOC_MODEL_ROOT"] = str(args.model_root)
    command = [str(args.dev_python), "-I", "-B", "-X", "utf8", str(REPO / "desktop" / "python" / "vietdoc_desktop_server.py"),
               "--repo-root", str(REPO), "--frontend-dist", str(REPO / "demo" / "local_pdf_ocr" / "frontend" / "dist"),
               "--model-lock", str(REPO / "desktop" / "model_lock.json"), "--paddlex-home", str(args.paddlex_home)]
    return command, env, str(REPO)


def multipart(path: Path, mode: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    content = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}[path.suffix.lower()]
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"mode\"\r\n\r\n{mode}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: {content}\r\n\r\n").encode("utf-8")
    return head + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


def label(path: Path, mode: str) -> str:
    """The full file name: a PNG and a JPG of the same page must not share a response file."""
    return f"{path.name}__{mode}"


def start_server(command: list[str], env: dict, cwd: str, token: str, out: Path):
    """Like the Electron shell: token on stdin; stderr (Paddle and server logs) goes to <out>/backend.log."""
    log = (out / "backend.log").open("ab")
    proc = subprocess.Popen(command, env=env, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    proc.stdin.write(token.encode("ascii") + b"\n")
    proc.stdin.flush()
    return proc, log


def run(args) -> dict:
    command, env, cwd = server_command(args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = {"server": "packaged" if args.app else "development", "app": str(args.app) if args.app else None,
              "documents": [], "result": "PASS"}
    token = secrets.token_hex(32)
    proc, log = start_server(command, env, cwd, token, out)
    try:
        line, seconds = read_line(proc, timeout=300)
        # Keep reading stdout after the ready line: a full pipe would block the backend mid-OCR.
        threading.Thread(target=lambda: log.write(proc.stdout.read()), daemon=True).start()
        if not line.startswith("VIETDOC_READY "):
            raise SystemExit(f"Backend did not start: {line} (log: {out / 'backend.log'})")
        port = json.loads(line.split(" ", 1)[1])["port"]
        status = json.loads(req(port, "GET", "/__desktop__/status", token)[2])
        report["startup_seconds"] = seconds
        report["status"] = {k: status.get(k) for k in ("ocr_allowed", "model_downloads", "runtime")}
        if status.get("ocr_allowed") is not True:
            report["result"] = "FAIL"
            report["error"] = f"OCR not allowed: {json.dumps(status, ensure_ascii=False)[:600]}"
            return report
        for item in args.doc:
            path, mode = item
            body, ctype = multipart(path, mode)
            started = time.monotonic()
            code, _, data = req_long(port, token, body, ctype)
            entry = {"document": path.name, "mode": mode, "status": code, "seconds": round(time.monotonic() - started, 1)}
            name = label(path, mode)
            if code == 200:
                result = json.loads(data)
                (out / f"{name}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
                if args.compare:
                    reference = Path(args.compare, f"{name}.json")
                    if reference.is_file():
                        diff = differences(strip_timing(result), strip_timing(json.loads(reference.read_text(encoding="utf-8"))))
                        entry["identical_to_reference"] = not diff
                        entry["differences"] = diff
                    else:
                        entry["identical_to_reference"] = None
                        entry["differences"] = ["no reference response"]
                    if entry["identical_to_reference"] is not True:
                        report["result"] = "FAIL"
            else:
                entry["detail"] = data.decode("utf-8", "replace")[:400]
                report["result"] = "FAIL"
            report["documents"].append(entry)
            print(json.dumps(entry, ensure_ascii=False), flush=True)
        req(port, "POST", "/__desktop__/shutdown", token)
        proc.wait(timeout=60)
        report["exit_code"] = proc.returncode
    finally:
        cleanup([proc])
        log.close()
        (out / "check_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return report


def req_long(port: int, token: str, body: bytes, ctype: str):
    import http.client
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1800)
    connection.putrequest("POST", "/api/ocr", skip_host=True, skip_accept_encoding=True)
    for key, value in (("Host", f"127.0.0.1:{port}"), ("X-VietDoc-Token", token), ("Content-Type", ctype),
                       ("Content-Length", str(len(body)))):
        connection.putheader(key, value)
    connection.endheaders()
    connection.send(body)
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response.status, dict(response.getheaders()), data


def document(value: str) -> tuple[Path, str]:
    path, _, mode = value.rpartition("=")
    if mode not in MODES or not path:
        raise argparse.ArgumentTypeError(f"expected <file>=<mode> with mode in {sorted(MODES)}: {value}")
    if not Path(path).is_file():
        raise argparse.ArgumentTypeError(f"no such file: {path}")
    return Path(path), mode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("--app", type=Path, help="folder holding VietDoc OCR.exe and resources/")
    where.add_argument("--dev-python", type=Path, help="development interpreter (reference run)")
    parser.add_argument("--model-root", type=Path)
    parser.add_argument("--paddlex-home", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--doc", type=document, action="append", required=True)
    parser.add_argument("--compare", type=Path)
    args = parser.parse_args()
    if args.dev_python and not (args.model_root and args.paddlex_home):
        parser.error("--dev-python needs --model-root and --paddlex-home")
    if args.app and os.environ.get("VIETDOC_MODEL_ROOT"):
        parser.error("unset VIETDOC_MODEL_ROOT: a packaged app must use its own bundled models")
    report = run(args)
    print(json.dumps({k: report.get(k) for k in ("server", "result", "startup_seconds", "error")}, ensure_ascii=False))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

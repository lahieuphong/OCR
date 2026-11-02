"""Black-box security probe of a packaged VietDoc backend (model-free).

Pass the packaged resources directory: win-unpacked/resources on Windows,
or VietDoc OCR.app/Contents/Resources on macOS. No models are downloaded.
The probe checks the request guard, loopback listener, security headers,
OCR refusal, graceful shutdown and the stdin watchdog.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import queue
import secrets
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import psutil

from process_network import process_connections


WINDOWS_KEEP = ("SystemRoot", "SystemDrive", "windir", "ComSpec", "PATHEXT", "TEMP", "TMP", "USERPROFILE",
                "LOCALAPPDATA", "APPDATA", "ProgramData", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS")
POSIX_KEEP = ("HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE")


def backend_command(resources: str, *, platform: str = sys.platform) -> str:
    name = "vietdoc-backend.exe" if platform == "win32" else "vietdoc-backend"
    return os.path.join(resources, "backend", "vietdoc-backend", name)


def probe_environment(exe: str, *, platform: str = sys.platform, source: dict | None = None) -> dict:
    """The frozen runtime must work without a user Python, shell PATH or loader overrides."""
    source = os.environ if source is None else source
    keep = WINDOWS_KEEP if platform == "win32" else POSIX_KEEP
    env = {key: source[key] for key in keep if key in source}
    if platform == "win32":
        import ntpath
        system = source.get("SystemRoot", r"C:\WINDOWS")
        own = ntpath.dirname(exe)
        entries = [own, ntpath.join(own, "_internal"), ntpath.join(system, "System32"), system,
                   ntpath.join(system, "System32", "Wbem")]
        separator = ";"
    else:
        import posixpath
        own = posixpath.dirname(exe)
        entries = [own, posixpath.join(own, "_internal"), "/usr/local/bin", "/usr/bin", "/bin"]
        separator = ":"
    env["PATH"] = separator.join(entry for entry in entries if separator not in entry)
    env["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    return env


def launch(args: list[str], env: dict, resources: str, token_line: str, *, platform: str = sys.platform):
    proc = subprocess.Popen(args, env=env, cwd=resources, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            creationflags=subprocess.CREATE_NO_WINDOW if platform == "win32" else 0)
    proc.stdin.write(token_line.encode() + b"\n")
    proc.stdin.flush()
    return proc


def read_line(proc, timeout=120):
    """Bound startup even when a native loader fails without writing a readiness line."""
    result = queue.Queue()
    started = time.monotonic()
    threading.Thread(target=lambda: result.put(proc.stdout.readline()), daemon=True).start()
    try:
        line = result.get(timeout=timeout)
    except queue.Empty as error:
        raise TimeoutError(f"Backend readiness timed out after {timeout} seconds") from error
    return line.decode("utf-8", "replace").strip(), round(time.monotonic() - started, 1)


def cleanup(processes):
    """Also clean up after failed assertions, malformed startup output or request timeouts."""
    for proc in processes:
        if proc.poll() is None:
            try:
                descendants = psutil.Process(proc.pid).children(recursive=True)
            except psutil.NoSuchProcess:
                descendants = []
            for child in reversed(descendants):
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            proc.kill()
            proc.wait(timeout=10)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()


def req(port, method, path, token=None, host=None, origin=None, body=None, ctype=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    c.putheader("Host", host if host is not None else f"127.0.0.1:{port}")
    if token is not None:
        c.putheader("X-VietDoc-Token", token)
    if origin is not None:
        c.putheader("Origin", origin)
    if body is not None:
        c.putheader("Content-Type", ctype)
        c.putheader("Content-Length", str(len(body)))
    c.endheaders()
    if body is not None:
        c.send(body)
    r = c.getresponse()
    data = r.read()
    headers = {k.lower(): v for k, v in r.getheaders()}
    c.close()
    return r.status, headers, data


def run_probe(resources: str, output: str, pdf: str) -> int:
    RES, OUT, PDF = resources, output, pdf
    EXE = backend_command(RES)
    EMPTY = os.path.join(os.path.dirname(OUT), "probe_paddlex_empty")
    os.makedirs(EMPTY, exist_ok=True)
    ENV = probe_environment(EXE)
    ARGS = [EXE, "--repo-root", RES, "--frontend-dist", os.path.join(RES, "frontend"),
            "--model-lock", os.path.join(RES, "model_lock.json"), "--paddlex-home", EMPTY]
    results = {"exe": EXE, "env_names": sorted(ENV), "checks": {}}
    C = results["checks"]
    processes = []

    def start(token_line):
        proc = launch(ARGS, ENV, RES, token_line)
        processes.append(proc)
        return proc

    try:
        # 1) malformed token -> refuses to start
        p = start("not-a-token")
        line, _ = read_line(p)
        p.wait(timeout=60)
        C["malformed_token_refused"] = {"line": line, "exit": p.returncode, "ok": line.startswith("VIETDOC_ERROR") and p.returncode != 0}

        # 2) normal start
        token = secrets.token_hex(32)
        p = start(token)
        line, secs = read_line(p)
        info = json.loads(line.split(" ", 1)[1]) if line.startswith("VIETDOC_READY ") else {}
        port = info.get("port")
        C["ready"] = {"line": line[:200], "seconds": secs, "ok": bool(port)}
        listen = []
        for proc in [psutil.Process(p.pid)] + psutil.Process(p.pid).children(recursive=True):
            for c in process_connections(proc):
                if c.status == psutil.CONN_LISTEN:
                    listen.append(f"{c.laddr.ip}:{c.laddr.port}")
        C["listen_loopback_only"] = {"method": "lsof" if sys.platform == "darwin" else "psutil", "listen": listen, "ok": bool(listen) and all(x.startswith("127.0.0.1:") for x in listen)}
        cases = {
            "ok_status": ("GET", "/__desktop__/status", token, None, None, 200),
            "no_token": ("GET", "/__desktop__/status", None, None, None, 403),
            "wrong_token": ("GET", "/__desktop__/status", secrets.token_hex(32), None, None, 403),
            "host_localhost": ("GET", "/__desktop__/status", token, f"localhost:{port}", None, 403),
            "host_rebinding": ("GET", "/__desktop__/status", token, "evil.example", None, 403),
            "origin_foreign": ("GET", "/__desktop__/status", token, None, "http://evil.example", 403),
            "origin_localhost": ("GET", "/__desktop__/status", token, None, f"http://localhost:{port}", 403),
            "origin_null": ("GET", "/__desktop__/status", token, None, "null", 403),
            "origin_same": ("GET", "/__desktop__/status", token, None, f"http://127.0.0.1:{port}", 200),
            "method_delete": ("DELETE", "/__desktop__/status", token, None, None, 403),
            "index_no_token": ("GET", "/", None, None, None, 403),
        }
        for name, (m, path, tok, host, origin, expect) in cases.items():
            st, hd, data = req(port, m, path, tok, host, origin)
            C[name] = {"status": st, "expected": expect, "ok": st == expect}
            if name == "ok_status":
                status = json.loads(data)
                C["status_payload"] = {k: status.get(k) for k in ("ocr_allowed", "model_downloads")}
                C["status_payload"]["ok"] = status.get("ocr_allowed") is False and status.get("model_downloads") == "disabled"
                C["security_headers"] = {k: hd.get(k) for k in ("content-security-policy", "x-content-type-options",
                                                                 "x-frame-options", "referrer-policy", "cache-control")}
        # 3) OCR without models must be refused
        boundary = uuid.uuid4().hex
        with open(PDF, "rb") as source:
            pdf = source.read()
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"mode\"\r\n\r\nvietocr_ocr\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"synthetic.pdf\"\r\n"
                f"Content-Type: application/pdf\r\n\r\n").encode() + pdf + f"\r\n--{boundary}--\r\n".encode()
        st, hd, data = req(port, "POST", "/api/ocr", token, body=body, ctype=f"multipart/form-data; boundary={boundary}")
        detail = data.decode("utf-8", "replace")[:300]
        C["ocr_without_models"] = {"status": st, "detail": detail, "ok": st == 503 and "chặn OCR" in detail}
        # This fixture deliberately has no administrative header. Fast inspection
        # must refuse required OCR, rather than accepting signature/ordinary text
        # as metadata or attempting a model download.
        fast_body = body.replace(b"\r\n\r\nvietocr_ocr\r\n", b"\r\n\r\nmetadata_fast\r\n", 1)
        st, _, data = req(port, "POST", "/api/ocr", token, body=fast_body, ctype=f"multipart/form-data; boundary={boundary}")
        detail = data.decode("utf-8", "replace")[:300]
        C["fast_without_models"] = {"status": st, "detail": detail, "ok": st == 503 and bool(detail)}
        # 4) graceful shutdown
        pids = [p.pid] + [c.pid for c in psutil.Process(p.pid).children(recursive=True)]
        st, _, _ = req(port, "POST", "/__desktop__/shutdown", token)
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            p.kill()
        time.sleep(1)
        C["shutdown"] = {"status": st, "exit": p.returncode, "alive_after": [x for x in pids if psutil.pid_exists(x)]}
        C["shutdown"]["ok"] = st == 200 and not C["shutdown"]["alive_after"]
        # 5) stdin watchdog: closing stdin (parent gone) stops the server
        p = start(secrets.token_hex(32))
        line, _ = read_line(p)
        pids = [p.pid] + [c.pid for c in psutil.Process(p.pid).children(recursive=True)]
        p.stdin.close()
        try:
            p.wait(timeout=30)
            exited = True
        except subprocess.TimeoutExpired:
            exited = False
            p.kill()
        time.sleep(1)
        C["stdin_watchdog"] = {"ready": line.startswith("VIETDOC_READY"), "exited": exited, "alive_after": [x for x in pids if psutil.pid_exists(x)]}
        C["stdin_watchdog"]["ok"] = exited and not C["stdin_watchdog"]["alive_after"]
        C["no_download_into_empty_paddlex_home"] = {"entries": os.listdir(EMPTY), "ok": not os.listdir(EMPTY)}
        results["all_ok"] = all(v.get("ok", True) for v in C.values() if isinstance(v, dict))
        with open(OUT, "w", encoding="utf-8") as output:
            json.dump(results, output, ensure_ascii=False, indent=1)
        # Console lines stay ASCII (\u escapes): a Windows runner's piped stdout is cp1252, and the server's Vietnamese
        # messages would otherwise crash the probe after the checks ran. The JSON file above keeps the real text.
        for k, v in C.items():
            print(f"{'PASS' if v.get('ok', True) else 'FAIL'} {k}: {json.dumps({x: y for x, y in v.items() if x != 'ok'})[:160]}")
        print("ALL_OK" if results["all_ok"] else "SOME_FAILED")
        return 0 if results["all_ok"] else 1
    finally:
        cleanup(processes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("resources")
    parser.add_argument("output")
    parser.add_argument("synthetic_pdf")
    args = parser.parse_args()
    return run_probe(str(Path(args.resources).resolve()), str(Path(args.output).resolve()),
                     str(Path(args.synthetic_pdf).resolve()))


if __name__ == "__main__":
    sys.exit(main())

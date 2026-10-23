"""Black-box security probe of a packaged vietdoc-backend.exe (model-free).

Starts the backend with a minimal environment (Windows essentials + controlled PATH, no Python/Node
on PATH, empty PaddleX home, no model root), then checks the request guard (token, Host, Origin,
method), security headers, the OCR refusal without models, the loopback-only listener, the malformed
token refusal, the stdin watchdog and the graceful shutdown. Prints and writes JSON.

Usage: python packaging/ci/probe_backend.py <win-unpacked\\resources> <out.json> <synthetic.pdf>
Exit code 0 only when every check passes. Needs psutil (pinned in requirements-packaging.txt).
"""
import http.client
import json
import os
import secrets
import subprocess
import sys
import time
import uuid

import psutil

RES, OUT, PDF = sys.argv[1:4]
EXE = os.path.join(RES, "backend", "vietdoc-backend", "vietdoc-backend.exe")
SR = os.environ.get("SystemRoot", r"C:\WINDOWS")
EMPTY = os.path.join(os.path.dirname(OUT), "probe_paddlex_empty")
os.makedirs(EMPTY, exist_ok=True)
KEEP = ["SystemRoot", "SystemDrive", "windir", "ComSpec", "PATHEXT", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA",
        "APPDATA", "ProgramData", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS"]
ENV = {k: os.environ[k] for k in KEEP if k in os.environ}
ENV["PATH"] = ";".join([os.path.dirname(EXE), SR + r"\System32", SR, SR + r"\System32\Wbem"])
ENV["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
ARGS = [EXE, "--repo-root", RES, "--frontend-dist", os.path.join(RES, "frontend"),
        "--model-lock", os.path.join(RES, "model_lock.json"), "--paddlex-home", EMPTY]
results = {"exe": EXE, "env_names": sorted(ENV), "checks": {}}
C = results["checks"]


def start(token_line):
    p = subprocess.Popen(ARGS, env=ENV, cwd=RES, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    p.stdin.write(token_line.encode() + b"\n")
    p.stdin.flush()
    return p


def read_line(p, timeout=120):
    t0 = time.time()
    line = p.stdout.readline().decode("utf-8", "replace").strip()
    return line, round(time.time() - t0, 1)


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
    for c in proc.net_connections(kind="inet"):
        if c.status == psutil.CONN_LISTEN:
            listen.append(f"{c.laddr.ip}:{c.laddr.port}")
C["listen_loopback_only"] = {"listen": listen, "ok": bool(listen) and all(x.startswith("127.0.0.1:") for x in listen)}
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
pdf = open(PDF, "rb").read()
body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"mode\"\r\n\r\nvietocr_ocr\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"synthetic.pdf\"\r\n"
        f"Content-Type: application/pdf\r\n\r\n").encode() + pdf + f"\r\n--{boundary}--\r\n".encode()
st, hd, data = req(port, "POST", "/api/ocr", token, body=body, ctype=f"multipart/form-data; boundary={boundary}")
detail = data.decode("utf-8", "replace")[:300]
C["ocr_without_models"] = {"status": st, "detail": detail, "ok": st == 503 and "chặn OCR" in detail}
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
json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for k, v in C.items():
    print(f"{'PASS' if v.get('ok', True) else 'FAIL'} {k}: {json.dumps({x: y for x, y in v.items() if x != 'ok'}, ensure_ascii=False)[:160]}")
print("ALL_OK" if results["all_ok"] else "SOME_FAILED")
sys.exit(0 if results["all_ok"] else 1)

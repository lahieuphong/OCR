"""Run a packaged VietDoc OCR build once and watch it from outside.

Records: exit code, elapsed time, every descendant process (name/exe), every TCP/UDP connection of
those processes whose remote address is not loopback, listening sockets, the environment-variable
NAMES of the backend process (plus the values of PATH and VIETDOC_*/PADDLE_* only), and processes
still alive after the app exits. Writes <out>/run_watch.json.

Usage:
  python packaging/ci/watch_run.py --exe <VietDoc OCR.exe> --out <dir> [--system-path | --system32-path] [--set K=V ...]
         [--unset K ...] [--timeout S] [--expect-exit N] [--strict] -- <app args...>
--strict fails (exit 1) on any non-loopback connection, any process left after exit, a timeout, or an exit
code other than --expect-exit (default 0). Needs psutil (pinned in requirements-packaging.txt).
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

import psutil

from process_network import process_connections

LOOPBACK = ("127.", "::1", "0.0.0.0", "::")


def is_loopback(addr):
    return (not addr) or addr.ip.startswith(LOOPBACK) or addr.ip in ("::ffff:127.0.0.1",)


def is_backend(name):
    return (name or "").lower() in {"vietdoc-backend", "vietdoc-backend.exe"}


def system_path(env, platform=sys.platform):
    if platform == "win32":
        # os.environ is case-insensitive on Windows, but dict(os.environ) is not.
        sr = next((value for name, value in env.items()
                   if name.upper() == "SYSTEMROOT" and value), r"C:\WINDOWS")
        return ";".join([sr + r"\System32", sr, sr + r"\System32\Wbem"])
    return "/usr/bin:/bin:/usr/sbin:/sbin"


def output_tail(stream, limit=2000):
    """Read bounded diagnostics from a file, without letting a full stdout pipe stall the app."""
    stream.seek(0, os.SEEK_END)
    stream.seek(max(0, stream.tell() - limit))
    return stream.read().decode("utf-8", "replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", required=True)
    ap.add_argument("--out", required=True)
    paths = ap.add_mutually_exclusive_group()
    paths.add_argument("--system32-path", action="store_true")
    paths.add_argument("--system-path", action="store_true",
                       help="use only OS system tools on PATH (no user Python or Node)")
    ap.add_argument("--set", action="append", default=[])
    ap.add_argument("--unset", action="append", default=[])
    ap.add_argument("--timeout", type=float, default=600)
    ap.add_argument("--expect-exit", type=int, default=0)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("app_args", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    args = [x for x in a.app_args if x != "--"]
    os.makedirs(a.out, exist_ok=True)
    env = dict(os.environ)
    for k in ["ELECTRON_RUN_AS_NODE"] + a.unset:
        for key in [x for x in env if x.upper() == k.upper()]:
            env.pop(key)
    if a.system32_path or a.system_path:
        for key in [x for x in env if x.upper() == "PATH"]:
            env.pop(key)
        env["PATH"] = system_path(env, "win32" if a.system32_path else sys.platform)
    for kv in a.set:
        k, v = kv.split("=", 1)
        env[k] = v
    build_dir = os.path.dirname(os.path.abspath(a.exe)).lower()
    t0 = time.time()
    monitoring_errors = {}

    def monitoring_error(pid, operation, error):
        monitoring_errors[(pid, operation)] = {"pid": pid, "operation": operation,
                                               "error": f"{type(error).__name__}: {error}"}
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        proc = subprocess.Popen([a.exe] + args, env=env, cwd=os.path.dirname(a.exe),
                                stdout=stdout_file, stderr=stderr_file)
        root = psutil.Process(proc.pid)
        seen, external, listening, backend_env = {}, [], set(), None
        while proc.poll() is None and time.time() - t0 < a.timeout:
            try:
                procs = [root] + root.children(recursive=True)
            except psutil.NoSuchProcess:
                procs = []
            except psutil.AccessDenied as error:
                monitoring_error(root.pid, "process_tree", error)
                procs = [root]
            for p in procs:
                try:
                    name = p.name()
                    if p.pid not in seen:
                        seen[p.pid] = {"name": name, "exe": p.exe(), "first_seen_s": round(time.time() - t0, 2)}
                except psutil.NoSuchProcess:
                    continue
                except psutil.AccessDenied as error:
                    monitoring_error(p.pid, "process_metadata", error)
                    name = str(p.pid)
                if backend_env is None and is_backend(name):
                    try:
                        e = p.environ()
                        backend_env = {"names": sorted(e), "count": len(e),
                                       "values": {k: v for k, v in e.items()
                                                  if k.upper() == "PATH" or k.upper().startswith(("VIETDOC_", "PADDLE_"))}}
                    except psutil.NoSuchProcess:
                        continue
                    except psutil.AccessDenied as error:
                        monitoring_error(p.pid, "backend_environment", error)
                try:
                    connections = process_connections(p)
                except psutil.NoSuchProcess:
                    continue
                except (psutil.AccessDenied, OSError, RuntimeError, subprocess.SubprocessError) as error:
                    monitoring_error(p.pid, "network", error)
                    continue
                for c in connections:
                    if c.status == psutil.CONN_LISTEN:
                        listening.add(f"{name} {c.laddr.ip}:{c.laddr.port}")
                    elif c.raddr and not is_loopback(c.raddr):
                        external.append({"pid": p.pid, "name": name, "raddr": f"{c.raddr.ip}:{c.raddr.port}",
                                         "status": c.status, "t": round(time.time() - t0, 2)})
            time.sleep(0.25)
        timed_out = proc.poll() is None
        if timed_out:
            proc.kill()
        proc.wait(timeout=30)
        out, err = output_tail(stdout_file), output_tail(stderr_file)
    elapsed = round(time.time() - t0, 1)
    time.sleep(3)  # give a graceful backend shutdown a moment before checking for leftovers
    leftovers = []
    for p in psutil.process_iter(["pid", "name", "exe"]):
        try:
            exe = (p.info["exe"] or "").lower()
            if p.info["pid"] in seen or exe.startswith(build_dir) or is_backend(p.info["name"]):
                leftovers.append({"pid": p.info["pid"], "name": p.info["name"], "exe": p.info["exe"]})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    res = {"exe": a.exe, "args": args, "exit_code": proc.returncode, "timed_out": timed_out, "elapsed_s": elapsed,
           "stdout": out, "stderr": err,
           "processes": list(seen.values()), "external_connections": external, "listening": sorted(listening),
           "backend_env": backend_env, "leftover_processes": leftovers,
           "monitoring_limitations": list(monitoring_errors.values()),
           "network_monitoring": {
               "method": "lsof" if sys.platform == "darwin" else "psutil",
               "complete": not any(item["operation"] in {"network", "process_tree"}
                                   for item in monitoring_errors.values()),
               "scope": "sampled observed app process tree; short-lived connections may be missed"},
           "launcher_env_path": env.get("PATH"), "launcher_env_extra": a.set}
    with open(os.path.join(a.out, "run_watch.json"), "w", encoding="utf-8") as output:
        json.dump(res, output, ensure_ascii=False, indent=1)
    print(json.dumps({k: res[k] for k in ("exit_code", "timed_out", "elapsed_s")}),
          "processes", len(seen), "external", len(external), "leftovers", len(leftovers),
          "backend_env_vars", backend_env and backend_env["count"])
    problems = []
    if not res["network_monitoring"]["complete"]:
        problems.append("network monitoring was incomplete; see monitoring_limitations")
    if timed_out:
        problems.append("timed out")
    if proc.returncode != a.expect_exit:
        problems.append(f"exit code {proc.returncode}, expected {a.expect_exit}")
    if external:
        problems.append(f"{len(external)} non-loopback connection(s): {external[:3]}")
    if leftovers:
        problems.append(f"processes left after exit: {leftovers}")
    for p in problems:
        print("PROBLEM:", p)
    return 1 if (a.strict and problems) else 0


if __name__ == "__main__":
    sys.exit(main())

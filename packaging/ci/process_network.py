"""Read sockets owned by one watched process without elevating the Electron app.

Darwin's protected-process APIs may reject psutil socket queries. Apple's lsof
can inspect sockets owned by the current user; machine-readable -F records
avoid relying on localized columns. A failed query is an error, never "no sockets".
See https://github.com/lsof-org/lsof/blob/master/docs/manpage.md#output-for-other-programs
"""
from __future__ import annotations

import subprocess
import sys
from collections import namedtuple

Address = namedtuple("Address", "ip port")
Connection = namedtuple("Connection", "laddr raddr status")


def address(value: str) -> Address:
    if value.startswith("["):
        host, separator, port = value[1:].rpartition("]:")
    else:
        host, separator, port = value.rpartition(":")
    if not separator or not host or not port.isdigit():
        raise RuntimeError(f"Unrecognized lsof socket address: {value!r}")
    return Address(host, int(port))


def parse_lsof(output: str, pid: int) -> list[Connection]:
    records, current = [], None

    def finish():
        if current is None:
            return
        if current.get("protocol") not in {"TCP", "UDP"}:
            raise RuntimeError("lsof returned an unrecognized socket protocol")
        name = current.get("name")
        if not name:
            raise RuntimeError("lsof returned a socket without an address")
        local, separator, remote = name.partition("->")
        records.append(Connection(address(local), address(remote) if separator else (),
                                  current.get("state", "NONE")))

    for line in output.splitlines():
        if not line:
            continue
        field, value = line[0], line[1:]
        if field == "p":
            finish()
            current = None
            if value != str(pid):
                raise RuntimeError("lsof returned sockets for a different process")
        elif field == "f":
            finish()
            current = {}
        elif current is not None:
            if field == "P":
                current["protocol"] = value
            elif field == "n":
                current["name"] = value
            elif field == "T" and value.startswith("ST="):
                current["state"] = value[3:]
    finish()
    return records


def process_connections(process, *, platform=sys.platform):
    if platform != "darwin":
        return process.net_connections(kind="inet")
    result = subprocess.run(["/usr/sbin/lsof", "-nP", "-a", "-p", str(process.pid), "-i", "-F", "pfnPT"],
                            capture_output=True, text=True, timeout=10)
    # lsof returns 1 when a valid selection has no matching open sockets.
    if result.returncode not in (0, 1) or result.stderr.strip():
        raise RuntimeError(f"lsof could not inspect process {process.pid}: {result.stderr.strip() or result.returncode}")
    if result.returncode == 1 and result.stdout.strip():
        raise RuntimeError(f"lsof returned incomplete socket output for process {process.pid}")
    return parse_lsof(result.stdout, process.pid)

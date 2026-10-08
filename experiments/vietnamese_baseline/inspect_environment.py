#!/usr/bin/env python3
"""Report the runtime environment of the Vietnamese PP-OCRv6 baseline as JSON.

Usage:
    python experiments/vietnamese_baseline/inspect_environment.py

Every probe is optional: a missing GPU, a missing ``nvidia-smi`` or a package
that is not installed is reported as ``null`` instead of raising.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VENDORED_PADDLEOCR = REPO_ROOT / "PaddleOCR"

# Upstream PaddlePaddle/PaddleOCR commit that PaddleOCR/ was imported from (see
# the repository's initial commit). The snapshot carries no git history, so
# this cannot be derived at runtime.
PADDLEOCR_UPSTREAM_SNAPSHOT = "dab3fe3537"


def _run(command: list[str], cwd: Path | None = None) -> str | None:
    """Return the stripped stdout of ``command``, or None if it cannot run."""
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip()


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cpu_name() -> str | None:
    if platform.system() == "Darwin":
        name = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
        if name:
            return name
    return platform.processor() or None


def total_ram_bytes() -> int | None:
    try:
        import psutil
    except ImportError:
        return None
    return int(psutil.virtual_memory().total)


def git_info() -> dict:
    """Branch, commit and dirtiness of the repository (None when unknown)."""
    status = _run(["git", "status", "--porcelain"], cwd=REPO_ROOT)
    return {
        "branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO_ROOT),
        "commit": _run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT),
        # Untracked files count as dirty: they can change what the scripts do.
        "dirty": None if status is None else bool(status),
    }


def paddle_info() -> dict:
    info = {
        "version": None,
        "device": None,
        "compiled_with_cuda": None,
        "cuda_version": None,
        "cudnn_version": None,
        "cuda_device_count": None,
    }
    try:
        import paddle
    except ImportError:
        return info

    info["version"] = paddle.__version__
    info["device"] = paddle.device.get_device()
    compiled_with_cuda = bool(paddle.is_compiled_with_cuda())
    info["compiled_with_cuda"] = compiled_with_cuda
    if compiled_with_cuda:
        info["cuda_version"] = str(paddle.version.cuda())
        info["cudnn_version"] = str(paddle.version.cudnn())
        info["cuda_device_count"] = int(paddle.device.cuda.device_count())
    else:
        info["cuda_device_count"] = 0
    return info


def paddleocr_info() -> dict:
    info = {"version": None, "import_path": None, "is_local_source": None}
    try:
        import paddleocr
    except ImportError:
        return info

    import_path = Path(paddleocr.__file__).resolve()
    info["version"] = paddleocr.__version__
    info["import_path"] = str(import_path)
    info["is_local_source"] = VENDORED_PADDLEOCR.resolve() in import_path.parents
    return info


def paddlex_version() -> str | None:
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:
        return None
    try:
        return version("paddlex")
    except PackageNotFoundError:
        return None


def nvidia_gpus() -> list[dict]:
    """GPUs reported by ``nvidia-smi``; empty when there is no NVIDIA stack."""
    if shutil.which("nvidia-smi") is None:
        return []
    output = _run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        ]
    )
    if not output:
        return []
    gpus = []
    for row in output.splitlines():
        fields = [field.strip() for field in row.split(",")]
        if len(fields) != 4:
            continue
        index, name, memory_mib, driver = fields
        gpus.append(
            {
                "index": int(index) if index.isdigit() else index,
                "name": name,
                "memory_total_mib": int(memory_mib) if memory_mib.isdigit() else None,
                "driver_version": driver,
            }
        )
    return gpus


def collect_environment() -> dict:
    git = git_info()
    return {
        "timestamp": utc_timestamp(),
        "platform": {
            "os": platform.system(),
            "os_release": platform.release(),
            "os_version": platform.mac_ver()[0] or platform.version(),
            "platform": platform.platform(),
            "architecture": platform.machine(),
            "cpu": cpu_name(),
            "cpu_count": os.cpu_count(),
            "ram_bytes": total_ram_bytes(),
        },
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
        },
        "paddle": paddle_info(),
        "paddlex_version": paddlex_version(),
        "paddleocr": paddleocr_info(),
        "nvidia_gpus": nvidia_gpus(),
        "repo": {
            "root": str(REPO_ROOT),
            "branch": git["branch"],
            "commit": git["commit"],
            "dirty": git["dirty"],
            "paddleocr_upstream_snapshot": PADDLEOCR_UPSTREAM_SNAPSHOT,
        },
    }


def main() -> int:
    print(json.dumps(collect_environment(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

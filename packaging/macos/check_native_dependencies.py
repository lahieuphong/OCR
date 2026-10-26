"""Verify the frozen backend's Mach-O dependencies need no build-machine libraries.

Usage: python check_native_dependencies.py <backend-folder> <report.json>
Reads load commands with Apple's otool; never modifies or signs a binary.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

MACHO_MAGICS = {bytes.fromhex(s) for s in (
    "feedface", "cefaedfe", "feedfacf", "cffaedfe", "cafebabe", "bebafeca", "cafebabf", "bfbafeca")}
LOAD_COMMANDS = {"LC_LOAD_DYLIB", "LC_LOAD_WEAK_DYLIB", "LC_REEXPORT_DYLIB",
                 "LC_LOAD_UPWARD_DYLIB", "LC_PREBOUND_DYLIB"}


def system_path(value: str) -> bool:
    return value.startswith(("/System/Library/", "/usr/lib/"))


def parse_load_commands(output: str) -> tuple[list[str], list[str]]:
    dependencies, rpaths = [], []
    command = ""
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("cmd "):
            command = line[4:]
        elif command in LOAD_COMMANDS and line.startswith("name "):
            dependencies.append(re.split(r" \(offset ", line[5:], maxsplit=1)[0])
        elif command == "LC_RPATH" and line.startswith("path "):
            rpaths.append(re.split(r" \(offset ", line[5:], maxsplit=1)[0])
    # LC_ID_DYLIB is the binary's own identity, never an imported dependency.
    return list(dict.fromkeys(dependencies)), list(dict.fromkeys(rpaths))


def macos_version(value: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,2}", value):
        raise ValueError(f"Invalid macOS version: {value}")
    parts = tuple(map(int, value.split(".")))
    return parts + (0,) * (3 - len(parts))


def parse_minimum_macos(output: str) -> list[str]:
    versions, command = [], ""
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("cmd "):
            command = line[4:]
        elif command == "LC_BUILD_VERSION" and line.startswith("minos "):
            versions.append(line.split()[1])
        elif command == "LC_VERSION_MIN_MACOSX" and line.startswith("version "):
            versions.append(line.split()[1])
    return list(dict.fromkeys(versions))


def load_commands(binary: Path) -> tuple[list[str], list[str], list[str]]:
    result = subprocess.run(["/usr/bin/otool", "-l", str(binary)], check=True,
                            capture_output=True, text=True, timeout=30)
    return (*parse_load_commands(result.stdout), parse_minimum_macos(result.stdout))


def expand_path(value: str, loader: Path, executable: Path) -> Path | None:
    for prefix, base in (("@loader_path", loader.parent), ("@executable_path", executable.parent)):
        if value == prefix:
            return base
        if value.startswith(prefix + "/"):
            return base.joinpath(*value[len(prefix) + 1:].split("/"))
    if value.startswith("/"):
        return Path(value)
    return None


def contained_file(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve(strict=True)
        return (resolved == root or root in resolved.parents) and resolved.is_file()
    except (OSError, RuntimeError):
        return False


def dependency_resolves(name: str, binary: Path, executable: Path, root: Path,
                        rpaths: list[tuple[str, Path]]) -> bool:
    if system_path(name):
        return True  # Apple's dyld shared cache may have no corresponding disk file.
    if name.startswith("/"):
        return False  # Even an existing build-machine path would break after relocation.
    if name.startswith("@rpath/"):
        suffix = name[len("@rpath/"):]
        for value, owner in rpaths:
            base = expand_path(value, owner, executable)
            if base is not None and contained_file(base.joinpath(*suffix.split("/")), root):
                return True
        return False
    target = expand_path(name, binary, executable)
    return target is not None and contained_file(target, root)


def audit(root: Path, *, reader=None, minimum_macos: str = "15.0") -> dict:
    supported = macos_version(minimum_macos)
    root = root.resolve(strict=True)
    executable = root / "vietdoc-backend"
    if not executable.is_file():
        raise ValueError("Frozen vietdoc-backend executable not found")
    reader = reader or load_commands
    cache = {}

    def commands(path):
        if path not in cache:
            cache[path] = reader(path)
        return cache[path]

    _, executable_rpaths, _ = commands(executable)
    findings, binaries, seen, requirements = [], 0, set(), []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError):
            findings.append({"path": rel, "reason": "broken or cyclic link"})
            continue
        if root not in resolved.parents and resolved != root:
            findings.append({"path": rel, "reason": "path escapes bundle"})
            continue
        if not resolved.is_file() or resolved in seen:
            continue
        seen.add(resolved)
        with resolved.open("rb") as stream:
            if stream.read(4) not in MACHO_MAGICS:
                continue
        binaries += 1
        dependencies, own_rpaths, minimum_versions = commands(resolved)
        for value in minimum_versions:
            requirements.append({"path": rel, "minimum_macos": value})
            if macos_version(value) > supported:
                findings.append({"path": rel, "reason": "requires a newer macOS", "minimum_macos": value})
        rpaths = [(value, resolved) for value in own_rpaths]
        rpaths += [(value, executable) for value in executable_rpaths]
        rpaths = list(dict.fromkeys(rpaths))
        for name in dependencies:
            if not dependency_resolves(name, resolved, executable, root, rpaths):
                findings.append({"path": rel, "reason": "unresolved or external dependency", "dependency": name})
        for value, owner in rpaths:
            expanded = expand_path(value, owner, executable)
            if system_path(value):
                continue
            if expanded is None or (expanded.resolve() != root and root not in expanded.resolve().parents):
                findings.append({"path": rel, "reason": "external or invalid rpath", "rpath": value})
    if not binaries:
        findings.append({"path": ".", "reason": "no Mach-O binaries found"})
    highest = max((item["minimum_macos"] for item in requirements), key=macos_version, default=None)
    return {"result": "FAIL" if findings else "PASS", "binaries": binaries,
            "supported_macos": minimum_macos, "highest_minimum_macos": highest,
            "minimum_versions": requirements, "findings": findings}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("bundle", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--minimum-macos", default="15.0",
                        help="oldest supported macOS; fail if any native binary requires newer")
    args = parser.parse_args()
    report = audit(args.bundle, minimum_macos=args.minimum_macos)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

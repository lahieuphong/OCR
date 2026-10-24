"""Turn the stderr of `python -X importtime` runs of the desktop server into runtime_modules.txt.

Paddle, PaddleX and PaddleOCR import many modules by name at run time, which PyInstaller's static analysis
cannot see; vietdoc-backend.spec adds every module listed in runtime_modules.txt as a hidden import.
Regenerate the list after any dependency change (see packaging/README.md):

    python importtime_modules.py <stderr.txt> [<stderr.txt> ...] > runtime_modules.txt
"""
from __future__ import annotations

import sys


def modules(lines) -> set[str]:
    """Module names from `import time: <self> | <cumulative> | <indented name>` lines."""
    found = set()
    for line in lines:
        if line.startswith("import time:") and line.count("|") == 2:
            name = line.rsplit("|", 1)[1].strip()
            if name and name != "imported package":
                found.add(name)
    return found


def main(paths: list[str]) -> None:
    names: set[str] = set()
    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as f:
            names |= modules(f)
    sys.stdout.reconfigure(newline="\n")  # the same file on every platform
    sys.stdout.write("".join(f"{name}\n" for name in sorted(names)))


if __name__ == "__main__":
    main(sys.argv[1:])

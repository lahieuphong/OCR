"""Make the benchmark scripts importable from the tests.

The scripts are run as files and import each other by module name, so the
tests put the same two directories on ``sys.path``.
"""

import sys
from pathlib import Path

BENCHMARK_DIR = Path(__file__).resolve().parents[1]
BAKEOFF_DIR = BENCHMARK_DIR / "recognizer_bakeoff"
REPO_ROOT = BENCHMARK_DIR.parents[1]

for directory in (BENCHMARK_DIR, BAKEOFF_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

"""Run the model-free backend tests of the local OCR app; fail on any failure, error or skip.

A skipped test means a required dependency was missing, which must not pass
silently in CI. Usage, from anywhere: python .github/scripts/run_backend_tests.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "demo" / "local_pdf_ocr" / "backend" / "tests"


def main() -> int:
    sys.path.insert(0, str(ROOT))
    suite = unittest.defaultTestLoader.discover(str(TESTS), pattern="test_*.py", top_level_dir=str(TESTS))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    problems = []
    if result.testsRun == 0:
        problems.append("no tests ran")
    for test, reason in result.skipped:
        problems.append(f"skipped: {test.id()} ({reason})")
    if result.failures or result.errors:
        problems.append(f"{len(result.failures)} failures, {len(result.errors)} errors")
    if problems:
        print("\nBACKEND TESTS NOT ACCEPTED:\n  " + "\n  ".join(problems))
        return 1
    print(f"\nBACKEND TESTS ACCEPTED: {result.testsRun} tests, no skips.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

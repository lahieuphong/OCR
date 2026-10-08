"""Make the dataset scripts importable from the tests."""

import sys
from pathlib import Path

DATASET_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = DATASET_DIR.parents[1]

if str(DATASET_DIR) not in sys.path:
    sys.path.insert(0, str(DATASET_DIR))

import dataset_common  # noqa: E402,F401  (also puts the benchmark scripts on the path)

"""The repository rules of the project: vendored code untouched, no documents in git."""

import subprocess
import unittest
from pathlib import PurePosixPath

import _paths

DOCUMENT_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp"}
WEIGHT_SUFFIXES = {".pdparams", ".pdiparams", ".pdmodel", ".pdopt", ".pth", ".pt", ".onnx", ".ckpt", ".safetensors"}
# Trees this project does not own: the vendored snapshot and the VietOCR submodule.
FOREIGN_TREES = ("PaddleOCR/", "third_party/")
LOCAL_ONLY = (".venv/", ".venv-vietocr/", "models/")


def git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=_paths.REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout


def project_files(*arguments: str) -> list[str]:
    return [
        path for path in git(*arguments, "-z").split("\0") if path and not path.startswith(FOREIGN_TREES)
    ]


class VendoredPaddleOCR(unittest.TestCase):
    def test_no_tracked_file_is_modified(self):
        self.assertEqual(git("diff", "HEAD", "--stat", "--", "PaddleOCR"), "")

    def test_no_file_is_added(self):
        self.assertEqual(git("status", "--porcelain", "--", "PaddleOCR"), "")


class NothingSensitiveCanBeCommitted(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Everything `git add -A` would put in a commit, plus what is staged now.
        cls.candidates = sorted(
            set(project_files("ls-files", "--cached", "--others", "--exclude-standard"))
            | set(project_files("diff", "--cached", "--name-only"))
        )

    def test_there_is_something_to_check(self):
        self.assertIn("benchmarks/vietnamese/recognizer_bakeoff/export_line_crops.py", self.candidates)

    def test_no_document_or_image(self):
        found = [path for path in self.candidates if PurePosixPath(path).suffix.lower() in DOCUMENT_SUFFIXES]
        self.assertEqual(found, [])

    def test_no_model_weights(self):
        found = [path for path in self.candidates if PurePosixPath(path).suffix.lower() in WEIGHT_SUFFIXES]
        self.assertEqual(found, [])

    def test_no_environment_or_download_directory(self):
        self.assertEqual([path for path in self.candidates if path.startswith(LOCAL_ONLY)], [])

    def test_no_large_file(self):
        large = [path for path in self.candidates if (_paths.REPO_ROOT / path).stat().st_size > 1_000_000]
        self.assertEqual(large, [])

    def test_crops_and_candidates_are_ignored(self):
        bakeoff = "benchmarks/vietnamese/recognizer_bakeoff"
        ignored = git(
            "check-ignore",
            f"{bakeoff}/crops/x_p0001_l0001.png",
            f"{bakeoff}/annotation/candidates/x_p0001_l0001.png",
            f"{bakeoff}/predictions/vietocr.jsonl",
            "models/vietocr/vgg_transformer.pth",
            ".venv-vietocr/pyvenv.cfg",
        ).splitlines()
        self.assertEqual(len(ignored), 5)

    def test_files_with_document_text_are_ignored(self):
        bakeoff = "benchmarks/vietnamese/recognizer_bakeoff"
        paths = [
            f"{bakeoff}/manifest.jsonl",
            f"{bakeoff}/annotation/manifest.tsv",
            f"{bakeoff}/annotation/annotation_log.jsonl",
            f"{bakeoff}/results/recognizer_errors.csv",
            f"{bakeoff}/results/edge_insertions.csv",
            f"{bakeoff}/results/recognizer_hard_cases.csv",
        ]
        self.assertEqual(len(git("check-ignore", *paths).splitlines()), len(paths))
        self.assertEqual([path for path in self.candidates if path in paths], [])


class PinnedVietOCR(unittest.TestCase):
    def test_submodule_is_at_the_recorded_commit(self):
        import run_vietocr

        head = git("-C", "third_party/vietocr", "rev-parse", "HEAD").strip()
        self.assertEqual(head, run_vietocr.VIETOCR_COMMIT)
        self.assertIn(run_vietocr.VIETOCR_COMMIT, git("submodule", "status", "third_party/vietocr"))

    def test_submodule_is_unmodified(self):
        self.assertEqual(git("-C", "third_party/vietocr", "status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()

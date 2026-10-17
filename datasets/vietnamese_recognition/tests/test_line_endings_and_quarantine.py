"""Frozen sets read the same on a CRLF checkout; quarantined labels stay out of training."""

import contextlib
import hashlib
import io
import tempfile
import unittest
from pathlib import Path

import _paths  # noqa: F401
import dataset_common as dataset
from dataset_common import BAKEOFF_REGRESSION, REAL_TRAIN, REAL_VAL


def temporary_directory(test: unittest.TestCase) -> Path:
    directory = tempfile.TemporaryDirectory()
    test.addCleanup(directory.cleanup)
    return Path(directory.name)


class FrozenSetLineEnds(unittest.TestCase):
    def setUp(self):
        self.root = temporary_directory(self)
        self.path = self.root / "bakeoff_regression.tsv"
        rows = [{"id": "a", "document": "d", "page": "1", "line_index": "1", "ground_truth": "Nghị định",
                 "crop_sha256": "0" * 64, "split": BAKEOFF_REGRESSION, "frozen": "true", "blind": "false"}]
        dataset.write_table(self.path, dataset.FROZEN_COLUMNS, rows)
        self.lock = self.path.with_suffix(".sha256")
        self.lock.write_text(f"{dataset.sha256_file(self.path)}  {self.path.name}\n", encoding="utf-8")

    def load(self):
        warnings = io.StringIO()
        with contextlib.redirect_stderr(warnings):
            rows = dataset.load_frozen(BAKEOFF_REGRESSION, self.path, self.lock)
        return rows, warnings.getvalue()

    def test_the_lf_file_loads_without_a_warning(self):
        rows, warnings = self.load()
        self.assertEqual(rows[0]["ground_truth"], "Nghị định")
        self.assertEqual(warnings, "")

    def test_a_crlf_checkout_loads_the_same_rows_and_says_so(self):
        expected, _ = self.load()
        self.path.write_bytes(self.path.read_bytes().replace(b"\n", b"\r\n"))
        self.assertNotEqual(dataset.sha256_file(self.path), self.lock.read_text(encoding="utf-8").split()[0])
        rows, warnings = self.load()
        self.assertEqual(rows, expected)
        self.assertIn("CRLF", warnings)

    def test_any_other_changed_byte_still_stops(self):
        for data in (self.path.read_bytes().replace("Nghị".encode(), "Nghi".encode()),
                     self.path.read_bytes().replace(b"\n", b"\r")):
            self.path.write_bytes(data)
            with self.assertRaisesRegex(SystemExit, "differs from the frozen version"):
                self.load()

    def test_text_digest_is_the_digest_of_the_lf_form(self):
        lf = self.path.read_bytes()
        self.path.write_bytes(lf.replace(b"\n", b"\r\n"))
        self.assertEqual(dataset.text_sha256(self.path), hashlib.sha256(lf).hexdigest())


class LabelQuarantine(unittest.TestCase):
    def setUp(self):
        self.root = temporary_directory(self)
        rows = {
            REAL_TRAIN: [dataset.manifest_row(id=f"t{n}", source_document="doc_t", image_path=f"crops/t{n}.png",
                                              text="quy định", split=REAL_TRAIN, source_type=dataset.REAL,
                                              verified="true") for n in range(3)],
            REAL_VAL: [dataset.manifest_row(id="v0", source_document="doc_v", image_path="crops/v0.png",
                                            text="Ủy ban", split=REAL_VAL, source_type=dataset.REAL, verified="true")],
        }
        for split, manifest in rows.items():
            dataset.write_manifest(dataset.manifest_path(split, self.root), manifest)
        self.train, self.valid = self.root / "train.txt", self.root / "valid.txt"
        self.train.write_text("".join(f"crops/t{n}.png\tquy định\n" for n in (0, 1, 1, 2)), encoding="utf-8")
        self.valid.write_text("crops/v0.png\tỦy ban\n", encoding="utf-8")

    def quarantine(self, *entries):
        rows = [{"id": i, "split": s, "reason": "diacritic_variant_screen", "status": status,
                 "opened": "2026-10-16", "note": ""} for i, s, status in entries]
        dataset.write_table(dataset.quarantine_path(self.root), dataset.QUARANTINE_COLUMNS, rows)

    def problems(self):
        return dataset.training_data_problems(self.train, self.valid, self.root, dataset.LEARNING_SPLITS)

    def test_no_quarantine_file_changes_nothing(self):
        self.assertEqual(self.problems(), [])
        self.assertEqual(dataset.open_quarantine(self.root), set())

    def test_an_open_entry_blocks_every_copy_of_the_line(self):
        self.quarantine(("t1", REAL_TRAIN, "open"), ("v0", REAL_VAL, "open"))
        problems = self.problems()
        self.assertEqual(len(problems), 2)
        self.assertIn("training file train.txt: 2 quarantined line(s)", problems[0])
        self.assertIn("validation file valid.txt: 1 quarantined line(s)", problems[1])

    def test_a_resolved_entry_no_longer_blocks(self):
        self.quarantine(("t1", REAL_TRAIN, "resolved"), ("v0", REAL_VAL, "resolved"))
        self.assertEqual(self.problems(), [])

    def test_an_unknown_status_stops(self):
        self.quarantine(("t1", REAL_TRAIN, "maybe"))
        with self.assertRaisesRegex(SystemExit, "unknown quarantine status"):
            self.problems()

    def test_quarantine_never_hides_an_evaluation_leak(self):
        self.quarantine(("t1", REAL_TRAIN, "open"))
        self.train.write_text("crops/v0.png\tỦy ban\ncrops/t1.png\tquy định\n", encoding="utf-8")
        problems = self.problems()
        self.assertIn("training file train.txt: 1 line(s) of real_val", problems)
        self.assertIn("quarantined", problems[-1])

    def test_a_training_run_on_the_repository_files_is_refused_while_their_lines_are_quarantined(self):
        ids = dataset.open_quarantine()
        configs = sorted(dataset.VIETOCR_CONFIG_DIR.glob("exp_*.yml"))
        train = dataset.MANIFESTS_DIR / "vietocr" / "train_mix_annotation.txt"
        valid = dataset.MANIFESTS_DIR / "vietocr" / "real_val_annotation.txt"
        if not ids or not configs or not train.is_file() or not valid.is_file():
            self.skipTest("no open quarantine or no generated training files in this checkout")
        images = {row["image_path"] for split in (REAL_TRAIN, REAL_VAL)
                  for row in dataset.read_manifest(dataset.manifest_path(split)) if row["id"] in ids}
        if not images & set(dataset.annotation_images(train) + dataset.annotation_images(valid)):
            self.skipTest("the generated files hold no quarantined line")
        problems = dataset.training_data_problems(train, valid, dataset.DATASET_DIR, dataset.LEARNING_SPLITS)
        self.assertTrue(any("quarantined" in problem for problem in problems))

    def test_the_repository_quarantine_only_names_known_open_lines(self):
        path = dataset.quarantine_path()
        if not path.is_file():
            self.skipTest("no quarantine in this checkout")
        rows = dataset.read_table(path, dataset.QUARANTINE_COLUMNS)
        known = {row["id"]: split for split in (REAL_TRAIN, REAL_VAL)
                 for row in dataset.read_manifest(dataset.manifest_path(split))}
        self.assertEqual([row["id"] for row in rows if known.get(row["id"]) != row["split"]], [])
        self.assertEqual(len({row["id"] for row in rows}), len(rows))


if __name__ == "__main__":
    unittest.main()

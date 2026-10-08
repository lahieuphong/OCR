"""The frozen evaluation sets: unchanged, and never part of training or validation."""

import contextlib
import io
import shutil
import tempfile
import unicodedata
import unittest
from pathlib import Path

import _paths  # noqa: F401
import dataset_common as dataset
import freeze_evaluation_set
from dataset_common import BAKEOFF_REGRESSION, BLIND_TEST, REAL_TRAIN, REAL_VAL, SYNTHETIC_TRAIN, SYNTHETIC_VAL

import bakeoff_common as bakeoff

# SHA-256 of bakeoff_regression.tsv as frozen. If this test fails the frozen
# ground truth was edited: restore the file, do not update the number.
FROZEN_SHA256 = "93f389002fe146fceaeb61f6acb7a162eb4359efcf4dc61094c0ad81a077b792"
# Digest of (id, ground truth, crop hash) of the 100 lines. It was the same
# when the set was still called the test holdout: giving the set its new role
# changed no label.
LABELS_SHA256 = "c8d06be982e6d77d02f9f7a9054e4ca5358d39f3de95b3e5701a611e6b83ca5a"


def temporary_directory(test: unittest.TestCase) -> Path:
    directory = tempfile.TemporaryDirectory()
    test.addCleanup(directory.cleanup)
    return Path(directory.name)


class BakeoffRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = dataset.load_frozen(BAKEOFF_REGRESSION)

    def test_file_is_the_one_that_was_frozen(self):
        path = dataset.frozen_path(BAKEOFF_REGRESSION)
        self.assertEqual(dataset.sha256_file(path), FROZEN_SHA256)
        self.assertEqual(path.with_suffix(".sha256").read_text(encoding="utf-8").split()[0], FROZEN_SHA256)

    def test_labels_are_those_verified_in_the_bakeoff(self):
        self.assertEqual(dataset.labels_digest(self.rows), LABELS_SHA256)

    def test_exactly_the_hundred_verified_lines(self):
        self.assertEqual(len(self.rows), 100)
        self.assertEqual(sum(len(row["ground_truth"]) for row in self.rows), 4853)
        self.assertEqual(sum(len(row["ground_truth"].split()) for row in self.rows), 1053)
        self.assertEqual({row["document"] for row in self.rows}, {"21-bct.signed", "216-tb.signed", "738-ttg.signed"})
        self.assertEqual(len({(row["document"], row["page"]) for row in self.rows}), 9)

    def test_role_is_regression_not_blind_test(self):
        self.assertEqual({(row["split"], row["frozen"], row["blind"]) for row in self.rows},
                         {(BAKEOFF_REGRESSION, "true", "false")})  # fmt: skip
        self.assertFalse((dataset.DATASET_DIR / "test_holdout").exists())

    def test_fields(self):
        self.assertEqual(tuple(self.rows[0]), dataset.FROZEN_COLUMNS)
        self.assertEqual(len({row["id"] for row in self.rows}), 100)
        self.assertEqual(len({row["crop_sha256"] for row in self.rows}), 100)
        for row in self.rows:
            self.assertTrue(row["ground_truth"])
            self.assertTrue(unicodedata.is_normalized("NFC", row["ground_truth"]))
            self.assertRegex(row["crop_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(row["id"], bakeoff.crop_id(row["document"], int(row["page"]), int(row["line_index"])))

    def test_no_image_is_stored_with_the_set(self):
        names = sorted(path.name for path in dataset.frozen_path(BAKEOFF_REGRESSION).parent.iterdir())
        self.assertEqual(names, ["bakeoff_regression.sha256", "bakeoff_regression.tsv", "source_documents.tsv"])

    def test_source_documents_are_recorded_by_hash(self):
        documents = dataset.benchmark_documents()
        self.assertEqual(sorted(documents.values()), ["21-bct.signed", "216-tb.signed", "738-ttg.signed"])
        self.assertTrue(all(len(digest) == 64 for digest in documents))


class Lock(unittest.TestCase):
    def copy(self) -> Path:
        root = temporary_directory(self) / BAKEOFF_REGRESSION
        root.mkdir()
        source = dataset.frozen_path(BAKEOFF_REGRESSION)
        shutil.copy(source, root / source.name)
        shutil.copy(source.with_suffix(".sha256"), root / source.with_suffix(".sha256").name)
        return root / source.name

    def test_an_edited_set_is_refused(self):
        path = self.copy()
        self.assertEqual(len(dataset.load_frozen(BAKEOFF_REGRESSION, path)), 100)
        path.write_text(path.read_text(encoding="utf-8").replace("năm", "nam", 1), encoding="utf-8")
        with self.assertRaises(SystemExit):
            dataset.load_frozen(BAKEOFF_REGRESSION, path)

    def test_a_set_without_lock_is_refused(self):
        path = self.copy()
        path.with_suffix(".sha256").unlink()
        with self.assertRaises(SystemExit):
            dataset.load_frozen(BAKEOFF_REGRESSION, path)

    def test_labels_digest_follows_labels_only(self):
        rows = dataset.load_frozen(BAKEOFF_REGRESSION)
        renamed = [{**row, "split": "anything", "frozen": "x"} for row in rows]
        self.assertEqual(dataset.labels_digest(renamed), LABELS_SHA256)
        edited = [dict(row) for row in rows]
        edited[0]["ground_truth"] += "."
        self.assertNotEqual(dataset.labels_digest(edited), LABELS_SHA256)

    def test_the_regression_set_cannot_be_frozen_again(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()) as refusal:
            freeze_evaluation_set.main([BAKEOFF_REGRESSION])  # not even offered as a choice
        self.assertIn("invalid choice", refusal.getvalue())


class LeakDetection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frozen = dataset.FrozenLines.load(BAKEOFF_REGRESSION)
        cls.line = cls.frozen.rows[0]

    def row(self, **fields) -> dict:
        return dataset.manifest_row(**{"id": "syn_train_000001", "text": "văn bản", "split": SYNTHETIC_TRAIN,
                                       "crop_sha256": "0" * 64, **fields})  # fmt: skip

    def test_clean_rows_pass(self):
        self.assertEqual(self.frozen.leaks([self.row(), self.row(id="syn_val_000001", split=SYNTHETIC_VAL)]), [])

    def test_a_frozen_id_is_caught_in_every_other_set(self):
        for split in (REAL_TRAIN, REAL_VAL, SYNTHETIC_TRAIN, SYNTHETIC_VAL, BLIND_TEST):
            problems = self.frozen.leaks([self.row(), self.row(id=self.line["id"], split=split)])
            self.assertEqual(len(problems), 1, split)
            self.assertIn(self.line["id"], problems[0])

    def test_a_frozen_image_under_another_id_is_caught(self):
        problems = self.frozen.leaks([self.row(id="renamed", crop_sha256=self.line["crop_sha256"])])
        self.assertEqual(len(problems), 1)
        self.assertIn("same SHA-256", problems[0])


@unittest.skipUnless(dataset.manifest_path(SYNTHETIC_TRAIN).is_file(), "the dataset has not been built")
class BuiltDataset(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frozen = dataset.FrozenLines.load(BAKEOFF_REGRESSION)
        cls.splits = dataset.read_splits()

    def other_sets(self):
        return [split for split in dataset.SPLITS if split != BAKEOFF_REGRESSION]

    def test_no_frozen_id_image_or_text_in_another_set(self):
        for split in self.other_sets():
            rows = self.splits[split]
            self.assertEqual({row["id"] for row in rows} & self.frozen.ids, set(), split)
            self.assertEqual({row["crop_sha256"] for row in rows} & self.frozen.hashes, set(), split)
        for split in (SYNTHETIC_TRAIN, SYNTHETIC_VAL):
            self.assertEqual({row["text"] for row in self.splits[split]} & self.frozen.texts, set(), split)

    def test_regression_manifest_is_exactly_the_frozen_set(self):
        self.assertEqual(
            {row["id"]: (row["text"], row["crop_sha256"]) for row in self.splits[BAKEOFF_REGRESSION]},
            {row["id"]: (row["ground_truth"], row["crop_sha256"]) for row in self.frozen.rows},
        )
        self.assertEqual({row["split"] for row in self.splits[BAKEOFF_REGRESSION]}, {BAKEOFF_REGRESSION})
        self.assertEqual({row["blind"] for row in self.splits[BAKEOFF_REGRESSION]}, {"false"})

    def test_the_old_test_manifest_is_gone(self):
        for name in ("train.tsv", "val.tsv", "test.tsv"):
            self.assertFalse((dataset.MANIFESTS_DIR / name).exists(), name)

    def test_training_annotation_files_hold_no_frozen_image(self):
        frozen_images = {row["image_path"] for row in self.splits[BAKEOFF_REGRESSION]}
        for name in ("train_mix", SYNTHETIC_TRAIN, SYNTHETIC_VAL, REAL_TRAIN, REAL_VAL):
            path = dataset.MANIFESTS_DIR / "vietocr" / f"{name}_annotation.txt"
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual({line.split("\t")[0] for line in lines} & frozen_images, set(), name)
            self.assertFalse(any("recognizer_bakeoff/crops" in line for line in lines), name)


if __name__ == "__main__":
    unittest.main()

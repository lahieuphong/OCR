"""The frozen test holdout: unchanged, and never part of training or validation."""

import shutil
import tempfile
import unicodedata
import unittest
from pathlib import Path

import _paths  # noqa: F401
import dataset_common as dataset
import freeze_test_holdout
from dataset_common import TEST, TRAIN, VAL

import bakeoff_common as bakeoff

# SHA-256 of test_holdout.tsv as frozen on 2026-10-08. If this test fails, the
# frozen ground truth was edited: restore the file, do not update the number.
FROZEN_SHA256 = "374f272db22dac2dd390cbe730135e400631ba85a36f3a753ec45c4e1912e04e"


def temporary_directory(test: unittest.TestCase) -> Path:
    directory = tempfile.TemporaryDirectory()
    test.addCleanup(directory.cleanup)
    return Path(directory.name)


class FrozenFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = dataset.load_holdout()

    def test_file_is_the_one_that_was_frozen(self):
        self.assertEqual(dataset.sha256_file(dataset.HOLDOUT), FROZEN_SHA256)
        self.assertEqual(dataset.HOLDOUT_LOCK.read_text(encoding="utf-8").split()[0], FROZEN_SHA256)

    def test_exactly_the_hundred_verified_lines(self):
        self.assertEqual(len(self.rows), 100)
        self.assertEqual(sum(len(row["ground_truth"]) for row in self.rows), 4853)
        self.assertEqual(sum(len(row["ground_truth"].split()) for row in self.rows), 1053)
        self.assertEqual(len({row["document"] for row in self.rows}), 3)
        self.assertEqual(len({(row["document"], row["page"]) for row in self.rows}), 9)

    def test_every_line_is_marked_test_and_frozen(self):
        self.assertEqual({(row["split"], row["frozen"]) for row in self.rows}, {(TEST, "true")})

    def test_fields(self):
        self.assertEqual(tuple(self.rows[0]), dataset.HOLDOUT_COLUMNS)
        self.assertEqual(len({row["id"] for row in self.rows}), 100)
        self.assertEqual(len({row["crop_sha256"] for row in self.rows}), 100)
        for row in self.rows:
            self.assertTrue(row["ground_truth"])
            self.assertTrue(unicodedata.is_normalized("NFC", row["ground_truth"]))
            self.assertRegex(row["crop_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(row["id"], bakeoff.crop_id(row["document"], int(row["page"]), int(row["line_index"])))

    def test_no_image_is_stored_with_the_holdout(self):
        self.assertEqual(sorted(path.name for path in dataset.HOLDOUT_DIR.iterdir()),
                         ["test_holdout.sha256", "test_holdout.tsv"])  # fmt: skip


class Lock(unittest.TestCase):
    def copy(self) -> tuple[Path, Path]:
        root = temporary_directory(self)
        shutil.copy(dataset.HOLDOUT, root / "test_holdout.tsv")
        shutil.copy(dataset.HOLDOUT_LOCK, root / "test_holdout.sha256")
        return root / "test_holdout.tsv", root / "test_holdout.sha256"

    def test_an_edited_holdout_is_refused(self):
        path, lock = self.copy()
        self.assertEqual(len(dataset.load_holdout(path, lock)), 100)
        path.write_text(path.read_text(encoding="utf-8").replace("năm", "nam", 1), encoding="utf-8")
        with self.assertRaises(SystemExit):
            dataset.load_holdout(path, lock)

    def test_a_holdout_without_lock_is_refused(self):
        path, lock = self.copy()
        lock.unlink()
        with self.assertRaises(SystemExit):
            dataset.load_holdout(path, lock)

    def test_freezing_twice_is_refused(self):
        path, lock = self.copy()
        before = path.read_bytes()
        with self.assertRaises(SystemExit):
            freeze_test_holdout.main(["--holdout", str(path), "--lock", str(lock)])
        self.assertEqual(path.read_bytes(), before)


class LeakDetection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.holdout = dataset.Holdout.load()
        cls.frozen = cls.holdout.rows[0]

    def row(self, **fields) -> dict:
        return dataset.manifest_row(**{"id": "syn_train_000001", "text": "văn bản", "split": TRAIN,
                                       "crop_sha256": "0" * 64, **fields})  # fmt: skip

    def test_clean_rows_pass(self):
        self.assertEqual(self.holdout.leaks([self.row(), self.row(id="syn_val_000001", split=VAL)]), [])

    def test_a_test_id_is_caught_in_train_and_in_val(self):
        for split in (TRAIN, VAL):
            problems = self.holdout.leaks([self.row(), self.row(id=self.frozen["id"], split=split)])
            self.assertEqual(len(problems), 1)
            self.assertIn(self.frozen["id"], problems[0])

    def test_a_test_image_under_another_id_is_caught(self):
        problems = self.holdout.leaks([self.row(id="renamed", crop_sha256=self.frozen["crop_sha256"])])
        self.assertEqual(len(problems), 1)
        self.assertIn("same SHA-256", problems[0])

    def test_no_test_line_can_enter_through_the_real_training_lines(self):
        # A person verifies, by mistake, a crop that belongs to the frozen test set.
        import build_dataset

        if not bakeoff.MANIFEST.is_file():
            self.skipTest("the bake-off crops are not on this machine")
        directory = temporary_directory(self)
        crops = {row["id"]: row for row in bakeoff.load_manifest()}
        other = next(key for key in crops if key not in self.holdout.ids)
        rows = []
        for key, text in ((self.frozen["id"], self.frozen["ground_truth"]), (other, "một dòng khác hẳn")):
            rows.append({
                "id": key, "document": crops[key]["document"], "page": str(crops[key]["page"]),
                "crop_path": crops[key]["crop_path"], "ppocr_prediction": "", "vietocr_prediction": "",
                "ground_truth": text, "verified": "true", "excluded_reason": "", "ground_truth_source": "typed",
                "annotator": "t", "verified_at": "", "ground_truth_sha256": bakeoff.text_sha256(text),
            })  # fmt: skip
        bakeoff.write_annotation(directory / "manifest.tsv", rows)
        kept, report = build_dataset.real_rows(self.holdout, directory, dataset.DATASET_DIR)
        self.assertEqual([row["id"] for row in kept], [other])
        self.assertEqual(report, {"verified": 1, "refused_as_test": 1})
        self.assertEqual(self.holdout.leaks(kept), [])


@unittest.skipUnless(dataset.manifest_path(TRAIN).is_file(), "the dataset has not been built")
class BuiltDataset(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.holdout = dataset.Holdout.load()
        cls.splits = {split: dataset.read_manifest(dataset.manifest_path(split)) for split in dataset.SPLITS}

    def test_no_frozen_id_in_train_or_val(self):
        for split in (TRAIN, VAL):
            self.assertEqual({row["id"] for row in self.splits[split]} & self.holdout.ids, set())

    def test_no_frozen_image_in_train_or_val(self):
        for split in (TRAIN, VAL):
            self.assertEqual({row["crop_sha256"] for row in self.splits[split]} & self.holdout.hashes, set())

    def test_no_frozen_text_in_train_or_val(self):
        for split in (TRAIN, VAL):
            self.assertEqual({row["text"] for row in self.splits[split]} & self.holdout.texts, set())

    def test_test_split_is_exactly_the_holdout(self):
        self.assertEqual(
            {row["id"]: (row["text"], row["crop_sha256"]) for row in self.splits[TEST]},
            {row["id"]: (row["ground_truth"], row["crop_sha256"]) for row in self.holdout.rows},
        )
        self.assertEqual({row["split"] for row in self.splits[TEST]}, {TEST})

    def test_vietocr_annotation_files_hold_no_test_image(self):
        test_images = {row["image_path"] for row in self.splits[TEST]}
        for name in ("train_annotation.txt", "val_annotation.txt"):
            lines = (dataset.MANIFESTS_DIR / "vietocr" / name).read_text(encoding="utf-8").splitlines()
            self.assertEqual({line.split("\t")[0] for line in lines} & test_images, set())
            self.assertFalse(any("recognizer_bakeoff/crops" in line for line in lines))


if __name__ == "__main__":
    unittest.main()

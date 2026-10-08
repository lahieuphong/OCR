"""The dataset audit: what it counts, and what makes it fail."""

import importlib.util
import tempfile
import unicodedata
import unittest
from pathlib import Path

import _paths  # noqa: F401
import audit_dataset
import build_dataset
import dataset_common as dataset
from dataset_common import REAL, TEST, TRAIN, VAL

HAS_IMAGING = all(importlib.util.find_spec(name) for name in ("cv2", "numpy", "PIL"))
VOCABULARY = build_dataset.recognizer_vocabulary()


class ResizeArithmetic(unittest.TestCase):
    def test_width_at_height_32(self):
        resized = audit_dataset.resized_width
        self.assertEqual(resized(320, 32, 512), (320, 1.0))
        self.assertEqual(resized(325, 32, 512), (330, 1.0))      # rounded up to a multiple of 10
        self.assertEqual(resized(10, 32, 512), (32, 1.0))        # never narrower than 32
        self.assertEqual(resized(1024, 32, 512), (512, 2.0))     # squeezed to half its width
        self.assertEqual(resized(1024, 32, 1024), (1024, 1.0))
        self.assertEqual(resized(900, 30, 512), (512, 960 / 512))

    def test_buckets(self):
        self.assertEqual(audit_dataset.bucket(16.0, audit_dataset.ASPECT_BUCKETS), "up to 16:1")
        self.assertEqual(audit_dataset.bucket(16.1, audit_dataset.ASPECT_BUCKETS), "16:1 to 24:1")
        self.assertEqual(audit_dataset.bucket(40, audit_dataset.ASPECT_BUCKETS), "over 32:1")
        self.assertEqual(audit_dataset.bucket(91, audit_dataset.LENGTH_BUCKETS), "91+")


@unittest.skipUnless(HAS_IMAGING, "OpenCV, NumPy and Pillow are needed to build a dataset")
class AuditOfABuiltDataset(unittest.TestCase):
    """Builds one small dataset, then breaks copies of it in specific ways."""

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        build_dataset.main(["--root", str(cls.root), "--scale", "0.02"])
        cls.holdout = dataset.Holdout.load()
        cls.original = {split: (cls.root / "manifests" / f"{split}.tsv").read_bytes() for split in dataset.SPLITS}

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def tearDown(self):
        for split, data in self.original.items():
            (self.root / "manifests" / f"{split}.tsv").write_bytes(data)

    def rows(self, split: str) -> list[dict]:
        return dataset.read_manifest(self.root / "manifests" / f"{split}.tsv")

    def audit_with(self, split: str, change) -> dict:
        rows = self.rows(split)
        change(rows)
        dataset.write_manifest(self.root / "manifests" / f"{split}.tsv", rows)
        return audit_dataset.audit(self.root, VOCABULARY)

    def test_the_untouched_dataset_passes(self):
        report = audit_dataset.audit(self.root, VOCABULARY)
        self.assertEqual((report["result"], report["failures"]), ("PASS", []))
        self.assertEqual(report["samples"][TEST], 100)
        self.assertEqual(report["samples"][TRAIN], len(self.rows(TRAIN)))
        self.assertEqual(report["duplicate_ids"], 0)
        self.assertEqual(report["duplicate_image_hashes"], 0)
        self.assertEqual(report["holdout"], {"lines": 100, "train_id_overlap": 0, "val_id_overlap": 0,
                                             "train_hash_overlap": 0, "val_hash_overlap": 0})  # fmt: skip
        self.assertEqual(report["texts_shared"], {"train_val": 0, "train_test": 0, "val_test": 0})
        letters = report["vietnamese_letters"]
        self.assertEqual((letters["reference"], letters["covered_in_train"], letters["missing_in_train"]), (178, 178, []))
        self.assertGreaterEqual(letters["minimum_occurrences_in_train"], 1)
        self.assertEqual(set(report["source_type"][TRAIN]), {"synthetic", "hard_case"})
        self.assertEqual(report["source_type"][TEST], {"real": 100})
        self.assertGreater(report["lines"][TRAIN]["long_line_subset"], 0)
        self.assertEqual(len(report["letter_counts"]), 178)
        self.assertEqual(audit_dataset.main(["--root", str(self.root)]), 0)

    def test_labels_are_nfc_and_images_match_their_hash(self):
        for split in (TRAIN, VAL):
            for row in self.rows(split):
                self.assertTrue(unicodedata.is_normalized("NFC", row["text"]))
                self.assertEqual(dataset.sha256_file(self.root / row["image_path"]), row["crop_sha256"])
                self.assertTrue((self.root / row["clean_image_path"]).is_file())
                self.assertEqual(row["verified"], "true")

    def test_a_frozen_test_id_in_training_fails(self):
        frozen = self.holdout.rows[0]["id"]
        report = self.audit_with(TRAIN, lambda rows: rows[0].update(id=frozen))
        self.assertEqual(report["result"], "FAIL")
        self.assertTrue(any("holdout leak" in failure and frozen in failure for failure in report["failures"]))
        self.assertEqual(report["holdout"]["train_id_overlap"], 1)
        self.assertEqual(audit_dataset.main(["--root", str(self.root), "--skip-images"]), 1)

    def test_a_frozen_test_image_in_validation_fails(self):
        frozen = self.holdout.rows[3]["crop_sha256"]
        report = self.audit_with(VAL, lambda rows: rows[0].update(crop_sha256=frozen))
        self.assertEqual(report["result"], "FAIL")
        self.assertEqual(report["holdout"]["val_hash_overlap"], 1)
        self.assertTrue(any("same SHA-256" in failure for failure in report["failures"]))

    def test_a_changed_test_manifest_fails(self):
        report = self.audit_with(TEST, lambda rows: rows[0].update(text=rows[0]["text"] + "!"))
        self.assertIn("the test manifest is not exactly the frozen holdout", report["failures"])

    def test_a_duplicate_id_fails(self):
        report = self.audit_with(TRAIN, lambda rows: rows[1].update(id=rows[0]["id"]))
        self.assertEqual(report["duplicate_ids"], 1)
        self.assertEqual(report["result"], "FAIL")

    def test_an_unverified_real_line_fails(self):
        report = self.audit_with(TRAIN, lambda rows: rows[0].update(source_type=REAL, verified="false"))
        self.assertTrue(any("no person verified" in failure for failure in report["failures"]))

    def test_a_label_that_is_not_nfc_fails(self):
        decomposed = unicodedata.normalize("NFD", "Việt Nam")
        report = self.audit_with(TRAIN, lambda rows: rows[0].update(text=decomposed))
        self.assertTrue(any("not NFC" in failure for failure in report["failures"]))

    def test_a_label_the_recognizer_cannot_encode_fails(self):
        report = self.audit_with(TRAIN, lambda rows: rows[0].update(text="giá 5 € mỗi chiếc"))
        self.assertTrue(any("outside the recognizer vocabulary" in failure for failure in report["failures"]))

    def test_a_label_longer_than_the_decoder_can_produce_fails(self):
        report = self.audit_with(TRAIN, lambda rows: rows[0].update(text="a" * 127))
        self.assertTrue(any("exceeds the decoder limit" in failure for failure in report["failures"]))

    def test_a_row_in_the_wrong_file_fails(self):
        report = self.audit_with(TRAIN, lambda rows: rows[0].update(split=VAL))
        self.assertTrue(any("split=val in train.tsv" in failure for failure in report["failures"]))

    def test_a_missing_image_fails(self):
        report = self.audit_with(TRAIN, lambda rows: rows[0].update(image_path="train/images/nope.png"))
        self.assertEqual(report["images_missing_or_changed"], 1)
        self.assertEqual(report["result"], "FAIL")

    def test_a_letter_absent_from_training_fails(self):
        def drop(rows):
            rows[:] = [row for row in rows if "ỵ" not in row["text"]]

        report = self.audit_with(TRAIN, drop)
        self.assertEqual(report["vietnamese_letters"]["missing_in_train"], ["ỵ"])
        self.assertIn("Vietnamese letter never seen in training: ỵ", report["failures"])

    def test_text_shared_with_the_test_set_is_a_warning_not_a_leak(self):
        frozen_text = self.holdout.rows[5]["ground_truth"]
        report = self.audit_with(TRAIN, lambda rows: rows[0].update(text=frozen_text))
        self.assertEqual(report["texts_shared"]["train_test"], 1)
        self.assertTrue(any("repeat a frozen test line" in warning for warning in report["warnings"]))
        self.assertFalse(any("holdout leak" in failure for failure in report["failures"]))

    def test_duplicate_texts_are_counted(self):
        report = self.audit_with(TRAIN, lambda rows: rows[1].update(text=rows[0]["text"]))
        self.assertEqual(report["duplicate_texts"][TRAIN], 1)
        self.assertEqual(report["unique_texts"][TRAIN], len(self.rows(TRAIN)) - 1)

    def test_building_again_gives_the_same_dataset(self):
        with tempfile.TemporaryDirectory() as other:
            build_dataset.main(["--root", other, "--scale", "0.02"])
            for split in dataset.SPLITS:
                self.assertEqual((Path(other) / "manifests" / f"{split}.tsv").read_bytes(), self.original[split], split)

    def test_vietocr_annotation_files_match_the_manifests(self):
        for split in (TRAIN, VAL):
            lines = (self.root / "manifests" / "vietocr" / f"{split}_annotation.txt").read_text(encoding="utf-8").splitlines()
            self.assertEqual([tuple(line.split("\t")) for line in lines],
                             [(row["image_path"], row["text"]) for row in self.rows(split)])  # fmt: skip


if __name__ == "__main__":
    unittest.main()

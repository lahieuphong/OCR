"""The dataset audit: what it reports for each of the six sets, and what makes it fail."""

import contextlib
import importlib.util
import io
import json
import tempfile
import unicodedata
import unittest
from pathlib import Path

import _paths  # noqa: F401
import audit_dataset
import build_dataset
import dataset_common as dataset
from _fixture import VOCABULARY, Workspace, document_id
from dataset_common import (
    BAKEOFF_REGRESSION,
    BLIND_TEST,
    REAL,
    REAL_TRAIN,
    REAL_VAL,
    SYNTHETIC_TRAIN,
    SYNTHETIC_VAL,
)

HAS_IMAGING = all(importlib.util.find_spec(name) for name in ("cv2", "numpy", "PIL"))


def quiet(function, *arguments):
    with contextlib.redirect_stdout(io.StringIO()) as output:
        status = function(*arguments)
    return status, output.getvalue()


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


class SixSets(unittest.TestCase):
    """A dataset with real lines in every set, then copies of it broken one way at a time."""

    def setUp(self):
        self.workspace = Workspace(self, {"t1": ("train", 6), "t2": ("train", 6), "v1": ("val", 6), "b1": ("blind", 6)})
        self.workspace.annotate(REAL_TRAIN, ["t1", "t2"], 4)
        self.workspace.annotate(REAL_VAL, ["v1"], 4)
        self.workspace.annotate(BLIND_TEST, ["b1"], 4)
        quiet(self.workspace.build)
        self.regression = dataset.FrozenLines.load(BAKEOFF_REGRESSION)

    def broken(self, split: str, change) -> dict:
        self.workspace.rewrite(split, change)
        return self.workspace.audit()

    def failures(self, split: str, change) -> str:
        report = self.broken(split, change)
        self.assertEqual(report["result"], "FAIL")
        self.assertFalse(report["readiness"]["ready"])
        return "\n".join(report["failures"])

    # --- what is reported --------------------------------------------------------

    def test_every_set_is_counted_separately(self):
        report = self.workspace.audit()
        self.assertEqual((report["result"], report["failures"]), ("PASS", []))
        self.assertEqual(report["samples"], {REAL_TRAIN: 8, REAL_VAL: 4, SYNTHETIC_TRAIN: 6, SYNTHETIC_VAL: 2,
                                             BAKEOFF_REGRESSION: 100, BLIND_TEST: 4})  # fmt: skip
        self.assertEqual(tuple(report["sets"]), (REAL_TRAIN, REAL_VAL, SYNTHETIC_TRAIN, SYNTHETIC_VAL, BAKEOFF_REGRESSION))
        self.assertEqual(report["blind_test"]["samples"], 4)
        self.assertEqual((report["duplicate_ids"], report["images_in_two_sets"], report["leak_failures"]), (0, 0, 0))

    def test_size_and_origin_of_a_set(self):
        report = self.workspace.audit()
        rows = self.workspace.splits()[REAL_TRAIN]
        train = report["sets"][REAL_TRAIN]
        self.assertEqual(train["characters"], sum(len(row["text"]) for row in rows))
        self.assertEqual(train["words"], sum(len(row["text"].split()) for row in rows))
        self.assertEqual(train["source_type"], {"real": 8})
        self.assertEqual(train["documents"], {document_id("t1"): 4, document_id("t2"): 4})
        self.assertEqual(report["sets"][REAL_VAL]["documents"], {document_id("v1"): 4})
        self.assertEqual(report["sets"][SYNTHETIC_TRAIN]["source_type"], {"synthetic": 6})
        self.assertEqual(report["sets"][SYNTHETIC_TRAIN]["fonts"], {"Times New Roman": 6})
        self.assertEqual(report["sets"][SYNTHETIC_TRAIN]["documents"], {})
        self.assertEqual(report["sets"][BAKEOFF_REGRESSION]["source_type"], {"real": 100})
        self.assertEqual(len(report["sets"][BAKEOFF_REGRESSION]["documents"]), 3)

    def test_length_and_aspect_distributions(self):
        train = self.workspace.audit()["sets"][REAL_TRAIN]
        self.assertEqual(sum(train["by_characters"].values()), 8)
        self.assertEqual(train["by_aspect_ratio"], {"up to 16:1": 8})  # crops of about 400 x 30 pixels
        self.assertEqual(train["longest_label"], max(len(row["text"]) for row in self.workspace.splits()[REAL_TRAIN]))
        self.assertEqual(train["wider_than_pretrained_limit"], 0)

    def test_documents_and_annotation_progress(self):
        report = self.workspace.audit()
        self.assertEqual(report["documents"], {
            "registered": 4, "by_split": {"train": 2, "val": 1, "blind": 1},
            "with_verified_lines": {REAL_TRAIN: 2, REAL_VAL: 1, BLIND_TEST: 1},
        })  # fmt: skip
        self.assertEqual(report["annotation"][REAL_TRAIN], {"selected": 12, "verified": 8, "skipped": 0, "pending": 4})
        self.assertEqual(report["annotation"][BLIND_TEST], {"selected": 6, "verified": 4, "skipped": 0, "pending": 2})

    def test_letter_coverage_per_set(self):
        letters = self.workspace.audit()["vietnamese_letters"]
        self.assertEqual((letters["reference"], letters["covered_in_training"], letters["missing_in_training"]), (178, 178, []))
        self.assertEqual(letters["covered"][SYNTHETIC_TRAIN], 178)
        self.assertLess(letters["covered"][REAL_VAL], 178)
        self.assertEqual(set(letters["covered"]), set(audit_dataset.OPEN_SPLITS))

    def test_resize_report_has_every_open_set_and_width(self):
        resize = self.workspace.audit()["resize"]
        self.assertEqual({(row["split"], row["max_width"]) for row in resize},
                         {(split, width) for split in audit_dataset.OPEN_SPLITS for width in (512, 768, 1024, 1280)})  # fmt: skip
        synthetic = {row["max_width"]: row for row in resize if row["split"] == SYNTHETIC_TRAIN}
        self.assertEqual((synthetic[512]["squeezed_lines"], synthetic[1024]["squeezed_lines"]), (6, 0))  # 600 x 30 pixels

    def test_the_command_prints_both_verdicts_and_writes_the_report(self):
        arguments = [*self.workspace.arguments(), "--legacy-dir", str(self.workspace.legacy_dir)]
        status, output = quiet(audit_dataset.main, arguments)
        self.assertEqual(status, 0)
        self.assertIn("DATA AUDIT: PASS", output)
        self.assertIn("TRAINING READY: NO", output)
        self.assertIn("NO  real_train_verified: 8 (required: 400)", output)
        self.assertIn("blind_test: 4 lines from 1 document(s); frozen: no; scores viewed: 0 time(s); content not reported", output)
        for split in audit_dataset.OPEN_SPLITS:
            self.assertIn(f"{split}: ", output)
        written = json.loads((self.workspace.root / "manifests" / "dataset_audit.json").read_text(encoding="utf-8"))
        self.assertEqual(written["blind_test"]["results_viewed"], 0)
        self.assertNotIn(BLIND_TEST, written["sets"])
        coverage = (self.workspace.root / "manifests" / "character_coverage.csv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(coverage[0], "char,unicode," + ",".join(audit_dataset.OPEN_SPLITS))
        self.assertEqual(len(coverage), 179)
        self.workspace.rewrite(REAL_TRAIN, lambda rows: rows[1].update(id=rows[0]["id"]))
        status, output = quiet(audit_dataset.main, arguments)
        self.assertEqual(status, 1)
        self.assertIn("DATA AUDIT: FAIL", output)
        self.assertIn("TRAINING READY: NO", output)

    # --- frozen lines ------------------------------------------------------------

    def test_a_bakeoff_line_id_in_training_fails(self):
        frozen = self.regression.rows[0]["id"]
        report = self.broken(SYNTHETIC_TRAIN, lambda rows: rows[0].update(id=frozen))
        self.assertTrue(any("bake-off regression leak" in failure and frozen in failure for failure in report["failures"]))
        self.assertGreater(report["leak_failures"], 0)

    def test_a_bakeoff_image_in_validation_fails(self):
        frozen = self.regression.rows[3]["crop_sha256"]
        failures = self.failures(REAL_VAL, lambda rows: rows[0].update(crop_sha256=frozen))
        self.assertIn("image of a bakeoff_regression line (same SHA-256)", failures)

    def test_a_changed_regression_manifest_fails(self):
        failures = self.failures(BAKEOFF_REGRESSION, lambda rows: rows[0].update(text=rows[0]["text"] + "!"))
        self.assertIn("the bakeoff_regression manifest is not exactly the frozen set", failures)

    def test_a_regression_line_dropped_from_its_manifest_fails(self):
        failures = self.failures(BAKEOFF_REGRESSION, lambda rows: rows.pop())
        self.assertIn("the bakeoff_regression manifest is not exactly the frozen set", failures)

    # --- identity ----------------------------------------------------------------

    def test_a_duplicate_id_fails(self):
        report = self.broken(REAL_TRAIN, lambda rows: rows[1].update(id=rows[0]["id"]))
        self.assertEqual((report["duplicate_ids"], report["result"]), (1, "FAIL"))

    def test_the_same_id_in_two_sets_fails(self):
        taken = self.workspace.splits()[REAL_VAL][0]["id"]
        report = self.broken(SYNTHETIC_VAL, lambda rows: rows[0].update(id=taken))
        self.assertEqual((report["duplicate_ids"], report["result"]), (1, "FAIL"))

    def test_an_image_repeated_inside_one_set_is_a_warning(self):
        report = self.broken(SYNTHETIC_TRAIN, lambda rows: rows[1].update(crop_sha256=rows[0]["crop_sha256"]))
        self.assertEqual(report["images_repeated_within_a_set"], 1)
        self.assertEqual(report["leak_failures"], 0)
        self.assertTrue(any("more than once within a set" in warning for warning in report["warnings"]))

    def test_a_row_in_the_wrong_file_fails(self):
        failures = self.failures(SYNTHETIC_TRAIN, lambda rows: rows[0].update(split=SYNTHETIC_VAL))
        self.assertIn("split=synthetic_val in synthetic_train.tsv", failures)

    def test_a_real_line_in_a_synthetic_set_fails(self):
        failures = self.failures(SYNTHETIC_TRAIN, lambda rows: rows[0].update(source_type=REAL))
        self.assertIn("a real line in synthetic_train", failures)

    def test_a_synthetic_line_in_a_real_set_fails(self):
        failures = self.failures(REAL_VAL, lambda rows: rows[0].update(source_type="synthetic"))
        self.assertIn("a synthetic line in real_val", failures)

    def test_an_unverified_real_line_fails(self):
        failures = self.failures(REAL_TRAIN, lambda rows: rows[0].update(verified="false"))
        self.assertIn("that no person verified", failures)

    def test_a_wrong_blind_flag_fails(self):
        self.assertIn("blind=true in real_train", self.failures(REAL_TRAIN, lambda rows: rows[0].update(blind="true")))
        self.assertIn("blind=false in blind_test", self.failures(BLIND_TEST, lambda rows: rows[0].update(blind="false")))

    def test_lines_of_a_document_registered_for_another_set_fail(self):
        documents = dataset.read_documents(self.workspace.documents_path)
        for document in documents:
            if document["document_id"] == document_id("t1"):
                document["split"] = "val"
        dataset.write_documents(documents, self.workspace.documents_path)
        report = self.workspace.audit()
        self.assertIn(f"{document_id('t1')} has lines in real_train but is registered for real_val", report["failures"])
        self.assertGreater(report["leak_failures"], 0)

    def test_a_document_flagged_blind_outside_the_blind_test_fails(self):
        documents = dataset.read_documents(self.workspace.documents_path)
        documents[0]["blind"] = "true" if documents[0]["blind"] == "false" else "false"
        dataset.write_documents(documents, self.workspace.documents_path)
        self.assertTrue(any("blind=" in failure for failure in self.workspace.audit()["failures"]))

    # --- labels and images -------------------------------------------------------

    def test_a_label_that_is_not_nfc_fails(self):
        decomposed = unicodedata.normalize("NFD", "Việt Nam")
        self.assertIn("label is not NFC", self.failures(REAL_TRAIN, lambda rows: rows[0].update(text=decomposed)))

    def test_an_empty_or_padded_label_fails(self):
        self.assertIn("empty label", self.failures(REAL_VAL, lambda rows: rows[0].update(text="")))
        self.assertIn("outer whitespace", self.failures(REAL_VAL, lambda rows: rows[0].update(text=" có khoảng trắng ")))

    def test_a_label_the_recognizer_cannot_encode_fails_unless_marked(self):
        failures = self.failures(SYNTHETIC_TRAIN, lambda rows: rows[0].update(text=rows[0]["text"] + " 5 €"))
        self.assertIn("characters outside the recognizer vocabulary: €", failures)
        report = self.broken(SYNTHETIC_TRAIN, lambda rows: rows[0].update(subset=audit_dataset.OUT_OF_VOCABULARY))
        self.assertEqual(report["result"], "PASS")
        self.assertTrue(any("hold a character the recognizer cannot output" in warning for warning in report["warnings"]))

    def test_a_label_longer_than_the_decoder_can_produce_fails(self):
        failures = self.failures(SYNTHETIC_VAL, lambda rows: rows[0].update(text="a" * 127))
        self.assertIn("exceeds the decoder limit", failures)

    def test_a_missing_image_fails(self):
        report = self.broken(SYNTHETIC_TRAIN, lambda rows: rows[0].update(image_path="train/images/nope.png"))
        self.assertEqual((report["images_missing_or_changed"], report["result"]), (1, "FAIL"))

    def test_a_changed_image_fails(self):
        row = self.workspace.splits()[REAL_VAL][0]
        (self.workspace.root / row["image_path"]).write_bytes(b"another image")
        report = self.workspace.audit()
        self.assertEqual((report["images_missing_or_changed"], report["result"]), (1, "FAIL"))
        self.assertTrue(any("image missing or changed" in failure for failure in report["failures"]))

    def test_a_letter_absent_from_training_fails(self):
        def drop(rows):
            for row in rows:
                row["text"] = row["text"].replace("ỵ", "y")

        report = self.broken(SYNTHETIC_TRAIN, drop)
        self.assertEqual(report["vietnamese_letters"]["missing_in_training"], ["ỵ"])
        self.assertIn("Vietnamese letter never seen in training: ỵ", report["failures"])

    def test_a_letter_seen_only_in_real_training_lines_counts(self):
        def drop(rows):
            for row in rows:
                row["text"] = row["text"].replace("ỵ", "y")

        self.workspace.rewrite(SYNTHETIC_TRAIN, drop)
        report = self.broken(REAL_TRAIN, lambda rows: rows[0].update(text=rows[0]["text"] + " ỵ"))
        self.assertEqual(report["vietnamese_letters"]["missing_in_training"], [])

    # --- text shared between sets --------------------------------------------------

    def test_text_shared_with_the_regression_set_is_a_warning_not_a_leak(self):
        frozen_text = self.regression.rows[5]["ground_truth"]
        report = self.broken(REAL_TRAIN, lambda rows: rows[0].update(text=frozen_text))
        self.assertEqual(report["texts_shared_between_sets"], {"real_train/bakeoff_regression": 1})
        self.assertEqual((report["result"], report["leak_failures"]), ("PASS", 0))

    def test_duplicate_texts_inside_a_set_are_counted(self):
        report = self.broken(REAL_TRAIN, lambda rows: rows[1].update(text=rows[0]["text"]))
        self.assertEqual(report["sets"][REAL_TRAIN]["duplicate_texts"], 1)
        self.assertEqual(report["sets"][REAL_TRAIN]["unique_texts"], 7)
        self.assertEqual(report["result"], "PASS")


class WhatATrainingRunMayRead(unittest.TestCase):
    def setUp(self):
        self.workspace = Workspace(self, {"t1": ("train", 6), "v1": ("val", 6), "b1": ("blind", 6)})
        self.workspace.annotate(REAL_TRAIN, ["t1"], 4)
        self.workspace.annotate(REAL_VAL, ["v1"], 4)
        self.workspace.annotate(BLIND_TEST, ["b1"], 4)
        quiet(self.workspace.build)
        self.files = self.workspace.root / "manifests" / "vietocr"

    def write(self, name: str, split: str) -> Path:
        path = self.files / name
        path.write_text("".join(f"{row['image_path']}\t{row['text']}\n" for row in self.workspace.splits()[split]), encoding="utf-8")
        return path

    def problems(self, train: Path, valid: Path) -> list[str]:
        return dataset.training_data_problems(train, valid, self.workspace.root)

    def test_evaluation_sets_get_no_trainer_readable_file(self):
        self.assertEqual(sorted(path.name for path in self.files.iterdir()), [
            "real_train_annotation.txt", "real_val_annotation.txt", "synthetic_train_annotation.txt",
            "synthetic_val_annotation.txt", "train_mix_annotation.txt",
        ])  # fmt: skip
        # One left over from an older build is removed by the next build.
        self.write("blind_test_annotation.txt", BLIND_TEST)
        quiet(self.workspace.build)
        self.assertFalse((self.files / "blind_test_annotation.txt").exists())

    def test_the_planned_files_are_accepted(self):
        self.assertEqual(self.problems(self.files / "train_mix_annotation.txt", self.files / "real_val_annotation.txt"), [])

    def test_blind_lines_in_training_or_validation_are_refused(self):
        blind = self.write("smuggled.txt", BLIND_TEST)
        self.assertEqual(self.problems(blind, self.files / "real_val_annotation.txt"),
                         ["training file smuggled.txt: 4 line(s) of blind_test"])  # fmt: skip
        self.assertEqual(self.problems(self.files / "train_mix_annotation.txt", blind),
                         ["validation file smuggled.txt: 4 line(s) of blind_test"])  # fmt: skip

    def test_regression_lines_in_training_are_refused(self):
        regression = self.write("smuggled.txt", BAKEOFF_REGRESSION)
        self.assertEqual(self.problems(regression, self.files / "real_val_annotation.txt"),
                         ["training file smuggled.txt: 100 line(s) of bakeoff_regression"])  # fmt: skip

    def test_validation_must_be_real_lines_only(self):
        problems = self.problems(self.files / "train_mix_annotation.txt", self.files / "synthetic_val_annotation.txt")
        self.assertEqual(problems, ["validation file synthetic_val_annotation.txt: 2 line(s) of synthetic_val"])
        problems = self.problems(self.files / "real_val_annotation.txt", self.files / "real_val_annotation.txt")
        self.assertEqual(problems, ["training file real_val_annotation.txt: 4 line(s) of real_val"])

    def test_an_image_no_manifest_knows_is_refused(self):
        stray = self.files / "stray.txt"
        stray.write_text("somewhere/else.png\tvăn bản\n", encoding="utf-8")
        self.assertEqual(self.problems(stray, self.files / "real_val_annotation.txt"), ["training file stray.txt: 1 line(s) of no set"])


@unittest.skipUnless(HAS_IMAGING, "OpenCV, NumPy and Pillow are needed to render a dataset")
class AuditOfARenderedDataset(unittest.TestCase):
    """Renders one small synthetic dataset, with no real document at all."""

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        cls.arguments = ["--root", str(cls.root), "--documents", str(cls.root / "real_documents.tsv"),
                         "--work-dir", str(cls.root / "real_work")]  # fmt: skip
        quiet(build_dataset.main, [*cls.arguments, "--scale", "0.02"])

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def audit(self) -> dict:
        return audit_dataset.audit(self.root, VOCABULARY, self.root / "real_documents.tsv", self.root / "real_work", self.root / "legacy")

    def test_it_passes_and_is_not_ready(self):
        report = self.audit()
        self.assertEqual((report["result"], report["failures"]), ("PASS", []))
        self.assertEqual((report["samples"][REAL_TRAIN], report["samples"][REAL_VAL], report["samples"][BLIND_TEST]), (0, 0, 0))
        self.assertEqual(report["samples"][BAKEOFF_REGRESSION], 100)
        self.assertGreater(report["samples"][SYNTHETIC_TRAIN], 100)
        letters = report["vietnamese_letters"]
        self.assertEqual((letters["covered_in_training"], letters["missing_in_training"]), (178, []))
        self.assertEqual(letters["covered"][REAL_VAL], 0)
        self.assertEqual(set(report["sets"][SYNTHETIC_TRAIN]["source_type"]), {"synthetic", "hard_case"})
        self.assertGreater(report["sets"][SYNTHETIC_TRAIN]["long_line_subset"], 0)
        self.assertGreater(len(report["sets"][SYNTHETIC_TRAIN]["fonts"]), 1)
        self.assertFalse(report["readiness"]["ready"])
        self.assertEqual(report["documents"]["registered"], 0)

    def test_labels_are_nfc_and_images_match_their_hash(self):
        for split in (SYNTHETIC_TRAIN, SYNTHETIC_VAL):
            for row in dataset.read_manifest(dataset.manifest_path(split, self.root)):
                self.assertTrue(unicodedata.is_normalized("NFC", row["text"]))
                self.assertEqual(dataset.sha256_file(self.root / row["image_path"]), row["crop_sha256"])
                self.assertTrue((self.root / row["clean_image_path"]).is_file())
                self.assertEqual((row["verified"], row["blind"]), ("true", "false"))

    def test_building_again_gives_the_same_dataset(self):
        with tempfile.TemporaryDirectory() as other:
            quiet(build_dataset.main, ["--root", other, "--documents", f"{other}/real_documents.tsv",
                                       "--work-dir", f"{other}/real_work", "--scale", "0.02"])  # fmt: skip
            for split in (SYNTHETIC_TRAIN, SYNTHETIC_VAL):
                self.assertEqual(dataset.manifest_path(split, Path(other)).read_bytes(),
                                 dataset.manifest_path(split, self.root).read_bytes(), split)  # fmt: skip

    def test_vietocr_files_match_the_manifests(self):
        for split in (SYNTHETIC_TRAIN, SYNTHETIC_VAL):
            lines = (self.root / "manifests" / "vietocr" / f"{split}_annotation.txt").read_text(encoding="utf-8").splitlines()
            rows = dataset.read_manifest(dataset.manifest_path(split, self.root))
            self.assertEqual([tuple(line.split("\t")) for line in lines], [(row["image_path"], row["text"]) for row in rows])
        # Without real lines a training pass is the synthetic training set and validation is empty.
        mix = (self.root / "manifests" / "vietocr" / "train_mix_annotation.txt").read_text(encoding="utf-8")
        self.assertEqual(mix, (self.root / "manifests" / "vietocr" / "synthetic_train_annotation.txt").read_text(encoding="utf-8"))
        self.assertEqual((self.root / "manifests" / "vietocr" / "real_val_annotation.txt").read_text(encoding="utf-8"), "")

    def test_keeping_the_synthetic_sets_leaves_them_untouched(self):
        before = {split: dataset.manifest_path(split, self.root).read_bytes() for split in (SYNTHETIC_TRAIN, SYNTHETIC_VAL)}
        quiet(build_dataset.main, [*self.arguments, "--skip-synthetic"])
        self.assertEqual({split: dataset.manifest_path(split, self.root).read_bytes() for split in before}, before)


if __name__ == "__main__":
    unittest.main()

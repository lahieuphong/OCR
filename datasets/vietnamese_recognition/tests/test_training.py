"""The fine-tuning wrapper: schedule, batches, selection, input digests, and its equivalence with the pinned trainer.

The tests that build the network need PyTorch and are skipped elsewhere; run this
file in the VietOCR environment to include them:

    .venv-vietocr/bin/python -m unittest discover -s datasets/vietnamese_recognition/tests -p "test_training.py"
"""

import argparse
import copy
import importlib.util
import json
import math
import sys
import tempfile
import types
import unittest
from collections import Counter
from pathlib import Path

import _paths  # noqa: F401
import build_vietocr_config as builder
import dataset_common as dataset
import train_vietocr as training
import training_inputs
import yaml

import run_vietocr

sys.dont_write_bytecode = True  # the pinned checkout stays free of bytecode files

HAS_TORCH = importlib.util.find_spec("torch") is not None
NEEDS_TORCH = "needs PyTorch: run this file with .venv-vietocr/bin/python"
EXPERIMENTS = ("exp_a_width512", "exp_b_width1024")
SOURCE = (dataset.DATASET_DIR / "train_vietocr.py").read_text(encoding="utf-8")


def experiment(name: str = EXPERIMENTS[0]) -> dict:
    return yaml.safe_load(builder.config_path(name).read_text(encoding="utf-8"))


def arguments(**changes) -> argparse.Namespace:
    values = {"smoke": False, "steps": None, "device": None, "batch_size": None, "accumulation_steps": None,
              "num_workers": None, "amp": False, "diagnostic_lines": None, "resume": False, "overwrite": False, "run_name": None,
              "freeze_batch_norm_statistics": False, "probe_memory": False}  # fmt: skip
    return argparse.Namespace(**{**values, **changes})


class Schedule(unittest.TestCase):
    def test_it_is_derived_from_the_finalized_training_pass(self):
        mix = json.loads((dataset.MANIFESTS_DIR / "build_report.json").read_text(encoding="utf-8"))["training_mix"]
        schedule = builder.schedule()
        self.assertEqual(schedule["samples_per_pass"], mix["samples_per_pass"])
        self.assertEqual(schedule["steps_per_epoch"], math.ceil(mix["samples_per_pass"] / schedule["effective_batch_size"]))
        self.assertEqual(schedule["total_steps"], schedule["epochs"] * schedule["steps_per_epoch"])
        self.assertEqual(schedule["validate_every"], schedule["steps_per_epoch"] // 2)

    def test_the_numbers_of_this_dataset(self):
        self.assertEqual(builder.schedule(), {"samples_per_pass": 7459, "effective_batch_size": 16, "steps_per_epoch": 467,
                                              "epochs": 10, "total_steps": 4670, "validate_every": 233})  # fmt: skip

    def test_both_configs_carry_it_and_the_old_budget_is_gone(self):
        for name in EXPERIMENTS:
            config = experiment(name)
            self.assertEqual(config["experiment"]["schedule"], builder.schedule(), name)
            self.assertEqual((config["trainer"]["iters"], config["trainer"]["valid_every"]), (4670, 233), name)
            self.assertNotEqual(config["trainer"]["iters"], 9500)
            self.assertEqual((config["trainer"]["batch_size"], config["experiment"]["accumulation_steps"]), (16, 1), name)
            self.assertEqual(config["optimizer"], {"max_lr": 0.0001, "pct_start": 0.1}, name)

    def test_the_experiments_still_differ_in_width_and_output_paths_only(self):
        first, second = (experiment(name) for name in EXPERIMENTS)
        for config in (first, second):
            config["dataset"].pop("image_max_width")
            config["experiment"].pop("name")
            for key in ("export", "checkpoint", "log"):
                config["trainer"].pop(key)
            config.pop("weights")
        self.assertEqual(first, second)


class Settings(unittest.TestCase):
    def test_a_full_run_follows_the_config(self):
        for name, width in zip(EXPERIMENTS, (512, 1024)):
            settings = training.resolve_settings(experiment(name), arguments())
            self.assertEqual((settings["mode"], settings["steps"], settings["scheduled_steps"], settings["validate_every"]), ("full", 4670, 4670, 233))
            self.assertEqual((settings["physical_batch_size"], settings["accumulation_steps"], settings["effective_batch_size"]), (16, 1, 16))
            self.assertEqual((settings["image_height"], settings["image_max_width"], settings["decoder_max_seq_length"]), (32, width, 128))
            self.assertEqual((settings["seed"], settings["max_lr"], settings["pct_start"]), (20261201, 0.0001, 0.1))
            self.assertEqual((settings["masked_language_model"], settings["image_aug"], settings["mixed_precision"]), (True, False, False))
            self.assertEqual(settings["batch_norm_statistics"], "frozen")  # the policy of both experiments

    def test_the_two_experiments_get_the_same_settings_but_for_the_width(self):
        first, second = (training.resolve_settings(experiment(name), arguments()) for name in EXPERIMENTS)
        different = {key for key in first if first[key] != second[key]}
        self.assertEqual(different, {"experiment", "image_max_width"})

    def test_a_smaller_batch_is_made_up_by_accumulation(self):
        settings = training.resolve_settings(experiment(), arguments(batch_size=4))
        self.assertEqual((settings["physical_batch_size"], settings["accumulation_steps"], settings["effective_batch_size"]), (4, 4, 16))
        settings = training.resolve_settings(experiment(), arguments(batch_size=8, accumulation_steps=2))
        self.assertEqual((settings["physical_batch_size"], settings["accumulation_steps"]), (8, 2))

    def test_the_effective_batch_cannot_be_changed_from_the_command_line(self):
        for changes in ({"batch_size": 8, "accumulation_steps": 1}, {"accumulation_steps": 2}, {"batch_size": 5}):
            with self.assertRaises(SystemExit) as refusal:
                training.resolve_settings(experiment(), arguments(**changes))
            self.assertIn("effective batch of 16", str(refusal.exception))

    def test_experiments_may_differ_in_width_only(self):
        first, second = (training.resolve_settings(experiment(name), arguments()) for name in EXPERIMENTS)
        self.assertEqual(training.unequal_settings(first, second), [])
        # The same effective batch out of another number of lines per pass is not the same experiment.
        smaller = training.resolve_settings(experiment(EXPERIMENTS[1]), arguments(batch_size=4))
        self.assertEqual(training.unequal_settings(first, smaller), ["physical_batch_size: 16 and 4", "accumulation_steps: 1 and 4"])
        updating = experiment(EXPERIMENTS[1])
        updating["experiment"]["batch_norm_statistics"] = "updated"
        updated = training.resolve_settings(updating, arguments())
        self.assertEqual(training.unequal_settings(first, updated), ["batch_norm_statistics: frozen and updated"])
        self.assertEqual(training.resolve_settings(updating, arguments(freeze_batch_norm_statistics=True))["batch_norm_statistics"], "frozen")
        mixed = training.resolve_settings(experiment(EXPERIMENTS[1]), arguments(amp=True))
        self.assertEqual(training.unequal_settings(first, mixed), ["mixed_precision: False and True"])
        # A report written before the setting existed was run the pinned trainer's way.
        older = {key: value for key, value in first.items() if key != "batch_norm_statistics"}
        self.assertEqual(training.unequal_settings(older, second), ["batch_norm_statistics: updated and frozen"])

    def test_both_configs_freeze_the_batch_norm_statistics(self):
        for name in EXPERIMENTS:
            self.assertEqual(experiment(name)["experiment"]["batch_norm_statistics"], "frozen", name)
        wrong = experiment()
        wrong["experiment"]["batch_norm_statistics"] = "half"
        with self.assertRaises(SystemExit):
            training.resolve_settings(wrong, arguments())

    def test_a_memory_probe_is_a_run_of_its_own(self):
        self.assertEqual(training.resolve_settings(experiment(), arguments(probe_memory=True, batch_size=8))["mode"], "probe")
        for extra in (["--smoke"], ["--resume"]):
            with self.assertRaises(SystemExit):
                training.main(["--config", str(builder.config_path(EXPERIMENTS[0])), "--probe-memory", *extra])

    def test_the_probe_takes_the_widest_lines_with_the_longest_labels(self):
        samples = [(f"{i}.png", "x" * length) for i, length in enumerate([5, 90, 40, 119, 7, 100, 60, 80, 30, 110])]
        buckets = {512: [0, 4], 1024: [1, 2, 3, 5, 6, 7, 8, 9]}
        batches = training.worst_case_batches(samples, buckets, 4, 3)
        self.assertEqual(batches[0], [3, 9, 5, 1])  # 119, 110, 100, 90 characters
        self.assertEqual(batches[1], [7, 6, 2, 8])
        self.assertEqual(batches[2], batches[0])  # the worst batches again when there are no more
        with self.assertRaises(SystemExit):
            training.worst_case_batches(samples, buckets, 16, 1)

    def test_a_smoke_run_is_the_start_of_the_real_schedule(self):
        settings = training.resolve_settings(experiment(), arguments(smoke=True))
        self.assertEqual((settings["mode"], settings["steps"], settings["scheduled_steps"]), ("smoke", 20, 4670))
        self.assertEqual(training.resolve_settings(experiment(), arguments(smoke=True, steps=30))["steps"], 30)
        with self.assertRaises(SystemExit):
            training.resolve_settings(experiment(), arguments(steps=30))  # a full run cannot be shortened

    def test_a_run_does_not_start_without_room_for_its_checkpoints(self):
        import shutil
        from unittest import mock

        usage = shutil.disk_usage(dataset.REPO_ROOT)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "not" / "created" / "yet"
            with mock.patch.object(shutil, "disk_usage", return_value=usage._replace(free=900 * 1024**2)):
                with self.assertRaises(SystemExit) as refusal:
                    training.check_disk_space(target)
            self.assertIn("900 MB free", str(refusal.exception))
            with mock.patch.object(shutil, "disk_usage", return_value=usage._replace(free=5000 * 1024**2)):
                self.assertEqual(training.check_disk_space(target), 5000)
            self.assertFalse(target.exists())  # checking creates nothing
        self.assertGreaterEqual(training.DISK_SPACE_NEEDED_MB, 1500)

    def test_smoke_runs_write_apart_from_the_real_run(self):
        config = experiment()
        full = training.output_directory(config, None)
        self.assertEqual(full, dataset.REPO_ROOT / "models" / "vietocr" / "finetuned" / "exp_a_width512")
        self.assertEqual(training.output_directory(config, "smoke"), full / "smoke")


class Batches(unittest.TestCase):
    BUCKETS = {320: list(range(0, 37)), 510: list(range(37, 50)), 100: list(range(50, 53)), 512: list(range(53, 120))}

    def sampler(self, **changes) -> training.ClusterBatches:
        return training.ClusterBatches(**{"buckets": self.BUCKETS, "batch_size": 4, "seed": 7, **changes})

    def width_of(self, index: int) -> int:
        return next(width for width, indices in self.BUCKETS.items() if index in indices)

    def test_a_batch_holds_lines_of_one_width_only(self):
        for batch in self.sampler().pass_batches(0):
            self.assertEqual(len(batch), 4)
            self.assertEqual(len({self.width_of(index) for index in batch}), 1)

    def test_incomplete_batches_of_a_width_are_left_out_of_the_pass(self):
        sampler = self.sampler()
        self.assertEqual(sampler.batches_per_pass, 37 // 4 + 13 // 4 + 3 // 4 + 67 // 4)
        used = Counter(self.width_of(index) for batch in sampler.pass_batches(0) for index in batch)
        self.assertEqual(used, {320: 36, 510: 12, 512: 64})  # the width with 3 lines never fills a batch of 4
        self.assertEqual(sampler.samples_per_pass, 112)
        indices = [index for batch in sampler.pass_batches(0) for index in batch]
        self.assertEqual(len(indices), len(set(indices)))  # no line twice within a pass

    def test_other_lines_are_left_out_in_another_pass(self):
        sampler = self.sampler()
        left_out = [set(range(120)) - {i for batch in sampler.pass_batches(number) for i in batch} for number in range(6)]
        self.assertGreater(len({frozenset(lines) for lines in left_out}), 1)
        self.assertTrue(all({50, 51, 52} <= lines for lines in left_out))

    def test_the_order_depends_on_the_seed_and_the_pass_only(self):
        self.assertEqual(self.sampler().pass_batches(3), self.sampler().pass_batches(3))
        self.assertNotEqual(self.sampler().pass_batches(3), self.sampler().pass_batches(4))
        self.assertNotEqual(self.sampler().pass_batches(0), self.sampler(seed=8).pass_batches(0))
        shuffled = dict(reversed(list(self.BUCKETS.items())))
        self.assertEqual(self.sampler(buckets=shuffled).pass_batches(2), self.sampler().pass_batches(2))

    def test_the_stream_goes_on_from_pass_to_pass(self):
        sampler = self.sampler()
        stream = iter(sampler)
        taken = [next(stream) for _ in range(2 * sampler.batches_per_pass + 3)]
        self.assertEqual(taken[: sampler.batches_per_pass], sampler.pass_batches(0))
        self.assertEqual(taken[sampler.batches_per_pass : 2 * sampler.batches_per_pass], sampler.pass_batches(1))
        self.assertEqual(taken[-3:], sampler.pass_batches(2)[:3])
        self.assertEqual([sampler.batch(number) for number in range(len(taken))], taken)

    def test_a_resumed_stream_is_the_rest_of_the_uninterrupted_one(self):
        whole = iter(self.sampler())
        uninterrupted = [next(whole) for _ in range(70)]
        for start in (1, 27, 28, 41, 69):
            resumed = iter(self.sampler(start=start))
            self.assertEqual([next(resumed) for _ in range(70 - start)], uninterrupted[start:], start)

    def test_a_batch_larger_than_every_width_is_refused(self):
        with self.assertRaises(SystemExit):
            self.sampler(batch_size=100)


class WhatIsOpened(unittest.TestCase):
    """The run finds out what its files hold without opening the manifest of an evaluation set."""

    def root(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for split in dataset.LEARNING_SPLITS:
            rows = [dataset.manifest_row(id=f"{split}{i}", text="x", split=split, image_path=f"{split}/{i}.png") for i in range(3)]
            dataset.write_manifest(dataset.manifest_path(split, root), rows)
        # Reading either of these would stop the test: they are not valid manifests.
        for split in (dataset.BLIND_TEST, dataset.BAKEOFF_REGRESSION):
            dataset.manifest_path(split, root).write_text("this file must not be read\n", encoding="utf-8")
        files = root / "manifests" / "vietocr"
        files.mkdir()
        (files / "train.txt").write_text("".join(f"{split}/{i}.png\tx\n" for split in dataset.TRAINING_SPLITS for i in range(3)), encoding="utf-8")
        (files / "valid.txt").write_text("".join(f"real_val/{i}.png\tx\n" for i in range(3)), encoding="utf-8")
        (files / "foreign.txt").write_text("blind_test/0.png\tx\nsomewhere/else.png\ty\n", encoding="utf-8")
        return root

    def test_the_planned_files_pass_without_the_evaluation_manifests(self):
        root = self.root()
        files = root / "manifests" / "vietocr"
        self.assertEqual(dataset.training_data_problems(files / "train.txt", files / "valid.txt", root, dataset.LEARNING_SPLITS), [])
        with self.assertRaises(SystemExit):  # whereas reading all six sets would have opened them
            dataset.training_data_problems(files / "train.txt", files / "valid.txt", root)

    def test_a_foreign_line_is_refused_all_the_same(self):
        root = self.root()
        files = root / "manifests" / "vietocr"
        self.assertEqual(dataset.training_data_problems(files / "foreign.txt", files / "valid.txt", root, dataset.LEARNING_SPLITS),
                         ["training file foreign.txt: 2 line(s) of no training or validation set"])  # fmt: skip
        self.assertEqual(dataset.training_data_problems(files / "train.txt", files / "foreign.txt", root, dataset.LEARNING_SPLITS),
                         ["validation file foreign.txt: 2 line(s) of no training or validation set"])  # fmt: skip
        self.assertEqual(dataset.training_data_problems(files / "train.txt", files / "train.txt", root, dataset.LEARNING_SPLITS),
                         ["validation file train.txt: 3 line(s) of real_train", "validation file train.txt: 3 line(s) of synthetic_train"])  # fmt: skip

    def test_the_wrapper_asks_for_those_four_sets_only(self):
        self.assertIn('data_root, dataset.LEARNING_SPLITS)', SOURCE)
        self.assertEqual(SOURCE.count("training_data_problems("), 1)
        self.assertEqual(dataset.LEARNING_SPLITS, ("real_train", "synthetic_train", "real_val", "synthetic_val"))


class Selection(unittest.TestCase):
    def result(self, cer: float, wer: float, exact: float = 0.5) -> dict:
        return {"cer_nfc": cer, "wer_nfc": wer, "exact_line_nfc": exact}

    def test_lower_real_validation_cer_wins(self):
        self.assertTrue(training.is_better(self.result(0.040, 0.20), self.result(0.045, 0.10)))
        self.assertFalse(training.is_better(self.result(0.046, 0.05), self.result(0.045, 0.10)))
        self.assertTrue(training.is_better(self.result(0.9, 0.9), None))  # the first candidate

    def test_a_tie_is_broken_by_wer(self):
        self.assertTrue(training.is_better(self.result(0.045, 0.09), self.result(0.045, 0.10)))
        self.assertFalse(training.is_better(self.result(0.045, 0.10), self.result(0.045, 0.10)))  # equal is not better

    def test_exact_line_accuracy_decides_nothing(self):
        self.assertFalse(training.is_better(self.result(0.050, 0.10, exact=0.99), self.result(0.045, 0.10, exact=0.10)))
        self.assertEqual(training.SELECTION_KEYS, ("cer_nfc", "wer_nfc"))

    def test_only_real_validation_lines_are_given_to_the_selection(self):
        self.assertIn("is_better(real, record[\"best\"][REAL_VAL] if record[\"best\"] else None)", SOURCE)
        self.assertEqual(SOURCE.count("is_better("), 2)  # its definition and that one call
        self.assertNotIn("is_better(synthetic", SOURCE)

    def test_the_blind_test_is_out_of_reach_of_the_wrapper(self):
        for forbidden in ("BLIND_TEST", "blind_test", "unlock", "read_splits(", "bakeoff_regression", "BAKEOFF_REGRESSION"):
            self.assertNotIn(forbidden, SOURCE, forbidden)
        imported = [line for line in SOURCE.splitlines() if line.startswith("from dataset_common import")]
        self.assertEqual(imported, ["from dataset_common import REAL_VAL, SYNTHETIC_VAL"])

    def test_validation_reads_the_two_validation_manifests_and_nothing_else(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for split in (dataset.REAL_VAL, dataset.SYNTHETIC_VAL):
                rows = [dataset.manifest_row(id=f"{split}{i}", text="x", split=split, image_path=f"{i}.png") for i in range(5)]
                dataset.write_manifest(dataset.manifest_path(split, root), rows)
            sets = training.validation_sets(root, None)  # no other manifest exists here, and none is asked for
            self.assertEqual({split: len(rows) for split, rows in sets.items()}, {dataset.REAL_VAL: 5, dataset.SYNTHETIC_VAL: 5})
            self.assertEqual(len(training.validation_sets(root, 2)[dataset.SYNTHETIC_VAL]), 2)
            self.assertEqual(len(training.validation_sets(root, 2)[dataset.REAL_VAL]), 5)  # the selection set is never shortened

    def test_it_does_not_call_the_pinned_trainer_or_patch_vietocr(self):
        self.assertNotIn("from vietocr.model.trainer", SOURCE)
        self.assertNotIn("import vietocr.model.trainer", SOURCE)
        for forbidden in ("__defaults__", "setattr(", "mock.patch", "monkeypatch"):
            self.assertNotIn(forbidden, SOURCE)


class InputDigests(unittest.TestCase):
    def test_what_is_recorded(self):
        self.assertEqual(set(training_inputs.DATASET_FILES), {"real_train", "real_val", "synthetic_train", "synthetic_val",
                                                              "train_mix_annotation", "real_val_annotation"})  # fmt: skip
        self.assertEqual(training_inputs.CONFIG_FILES, ("exp_a_width512.yml", "exp_b_width1024.yml", "data_mix.yml"))
        self.assertEqual(training_inputs.PRETRAINED, "models/vietocr/vgg_transformer.pth")
        self.assertEqual(training_inputs.SHARED, ("dataset", "pretrained"))

    def digests(self, **changes) -> dict:
        base = {"dataset": {"real_train": {"sha256": "a" * 64}, "real_val": {"sha256": "b" * 64}},
                "configs": {"exp_a_width512.yml": {"sha256": "c" * 64}, "exp_b_width1024.yml": {"sha256": "d" * 64}},
                "pretrained": {"sha256": "e" * 64}}  # fmt: skip
        result = copy.deepcopy(base)
        for key, value in changes.items():
            part, _, name = key.partition("__")
            if name:
                result[part][name]["sha256"] = value
            else:
                result[part]["sha256"] = value
        return result

    def test_identical_inputs_have_no_difference(self):
        self.assertEqual(training_inputs.differences(self.digests(), self.digests()), [])

    def test_a_changed_file_is_named(self):
        changed = training_inputs.differences(self.digests(), self.digests(dataset__real_val="f" * 64))
        self.assertEqual(len(changed), 1)
        self.assertTrue(changed[0].startswith("dataset/real_val: recorded bbbbbbbb"))
        self.assertEqual(len(training_inputs.differences(self.digests(), self.digests(pretrained="0" * 64))), 1)

    def test_experiments_share_data_and_weights_not_their_config(self):
        other_config = self.digests(configs__exp_a_width512__yml="0" * 64) if False else self.digests()
        other_config["configs"]["exp_a_width512.yml"]["sha256"] = "0" * 64
        self.assertEqual(training_inputs.differences(self.digests(), other_config, training_inputs.SHARED), [])
        self.assertEqual(len(training_inputs.differences(self.digests(), other_config)), 1)
        other_data = self.digests(dataset__real_train="0" * 64)
        self.assertEqual(len(training_inputs.differences(self.digests(), other_data, training_inputs.SHARED)), 1)

    def test_the_frozen_record_matches_the_files(self):
        if not training_inputs.LOCK.is_file():
            self.skipTest("the training inputs are not frozen yet")
        missing = [name for name, relative in training_inputs.DATASET_FILES.items() if not (dataset.DATASET_DIR / relative).is_file()]
        if missing or not (dataset.REPO_ROOT / training_inputs.PRETRAINED).is_file():
            self.skipTest("this machine does not hold the generated files or the weights")
        self.assertEqual(training_inputs.differences(training_inputs.load(), training_inputs.current()), [])
        recorded = training_inputs.load()
        self.assertEqual(recorded["pretrained"]["sha256"], run_vietocr.WEIGHTS_SHA256)
        self.assertEqual(recorded["dataset"]["train_mix_annotation"]["lines"], 7459)
        self.assertEqual((recorded["dataset"]["real_train"]["lines"], recorded["dataset"]["real_val"]["lines"]), (403, 101))  # with the header

    def test_freezing_checking_and_refusing_to_overwrite(self):
        if not (dataset.REPO_ROOT / training_inputs.PRETRAINED).is_file() or not (dataset.MANIFESTS_DIR / "vietocr" / "train_mix_annotation.txt").is_file():
            self.skipTest("this machine does not hold the generated files or the weights")
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            lock = Path(directory) / "inputs.json"
            self.assertEqual(training_inputs.main(["--lock", str(lock)]), 0)
            self.assertEqual(training_inputs.main(["--lock", str(lock), "--check"]), 0)
            record = json.loads(lock.read_text(encoding="utf-8"))
            record["dataset"]["real_val"]["sha256"] = "0" * 64
            lock.write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(training_inputs.main(["--lock", str(lock), "--check"]), 1)
            with self.assertRaises(SystemExit):
                training_inputs.main(["--lock", str(lock)])  # a record that differs is not replaced silently
            self.assertEqual(training_inputs.main(["--lock", str(lock), "--force"]), 0)
            self.assertEqual(training_inputs.main(["--lock", str(lock), "--check"]), 0)


# --- with the network ---------------------------------------------------------------


def use_pinned_checkout() -> None:
    if str(run_vietocr.VIETOCR_DIR) not in sys.path:
        sys.path.insert(0, str(run_vietocr.VIETOCR_DIR))


def pinned_collator():
    """VietOCR's own ``Collator``. Its module also imports what only the LMDB reader needs."""
    absent = [name for name in ("lmdb", "six", "cv2") if importlib.util.find_spec(name) is None]
    for name in absent:
        sys.modules[name] = types.ModuleType(name)
    try:
        from vietocr.loader.dataloader import Collator
    finally:
        for name in absent:  # only the stand-ins go; everything really imported stays imported
            del sys.modules[name]
    return Collator


LABELS = ("Số: 15/2024/NĐ-CP", "Căn cứ Luật Tổ chức Chính phủ ngày 19 tháng 6 năm 2015;", "QUYẾT ĐỊNH", "Điều 3. Hiệu lực thi hành")


@unittest.skipUnless(HAS_TORCH, NEEDS_TORCH)
class CheckpointRngRestore(unittest.TestCase):
    def test_cuda_mapped_rng_tensors_are_moved_back_to_cpu(self):
        """A CUDA map_location cannot change the required RNG setter input device."""
        import torch
        from unittest.mock import Mock, patch

        class PretendCudaTensor:
            def __init__(self, original):
                self.original = original

            def cpu(self):
                return self.original

        original_cpu_rng = torch.get_rng_state().clone()
        state = {
            "model": {}, "optimizer": {}, "scheduler": {}, "scaler": None,
            "torch_rng": PretendCudaTensor(original_cpu_rng),
            "cuda_rng": [PretendCudaTensor(original_cpu_rng)],
        }
        with patch.object(torch.cuda, "is_available", return_value=True), \
                patch.object(torch.cuda, "set_rng_state_all") as set_cuda:
            training.restore_state(state, Mock(), Mock(), Mock(), None)
        self.assertTrue(torch.equal(torch.get_rng_state(), original_cpu_rng))
        set_cuda.assert_called_once()
        self.assertTrue(torch.equal(set_cuda.call_args.args[0][0], original_cpu_rng))


@unittest.skipUnless(HAS_TORCH, NEEDS_TORCH)
class LikeThePinnedTrainer(unittest.TestCase):
    """The parts that mirror VietOCR's code give what VietOCR's code gives."""

    @classmethod
    def setUpClass(cls):
        use_pinned_checkout()
        from vietocr.model.vocab import Vocab

        cls.config = experiment()
        cls.config["device"] = "cpu"
        cls.config["cnn"]["pretrained"] = False
        cls.vocab = Vocab(cls.config["vocab"])
        cls.Collator = pinned_collator()

    def samples(self, width: int = 96) -> list[dict]:
        import numpy

        rng = numpy.random.RandomState(3)
        return [{"img": rng.random_sample((3, 32, width)).astype(numpy.float32), "word": self.vocab.encode(label), "img_path": f"{i}.png"}
                for i, label in enumerate(LABELS)]  # fmt: skip

    def assert_same_batch(self, first: dict, second: dict) -> None:
        import torch

        for key in ("img", "tgt_input", "tgt_output", "tgt_padding_mask"):
            self.assertEqual(first[key].dtype, second[key].dtype, key)
            self.assertTrue(torch.equal(first[key], second[key]), key)
        self.assertEqual(first["filenames"], second["filenames"])

    def test_collation_is_the_collators(self):
        self.assert_same_batch(training.collate(self.samples()), self.Collator(masked_language_model=False)(self.samples()))

    def test_masking_is_the_collators_given_the_same_random_numbers(self):
        import numpy

        for seed, number in ((20261201, 0), (20261201, 17), (5, 3)):
            numpy.random.seed([seed % 2**32, number])
            expected = self.Collator(masked_language_model=True)(self.samples())
            batch = training.collate(self.samples())
            training.mask_tokens(batch["tgt_input"], seed, number)
            self.assert_same_batch(batch, expected)

    def test_masks_depend_on_the_seed_and_the_batch_number_and_spare_special_tokens(self):
        import torch

        def masked(seed: int, number: int):
            batch = training.collate(self.samples())
            before = batch["tgt_input"].clone()
            count = training.mask_tokens(batch["tgt_input"], seed, number)
            return before, batch["tgt_input"], count

        before, first, count = masked(1, 0)
        self.assertTrue(torch.equal(first, masked(1, 0)[1]))
        self.assertFalse(all(torch.equal(first, masked(1, number)[1]) for number in range(1, 6)))
        changed = first != before
        self.assertEqual(int(changed.sum()), count)
        self.assertTrue(bool((first[changed] == 3).all()))
        self.assertFalse(bool(((before == 0) | (before == 1) | (before == 2))[changed].any()))
        total = sum(masked(1, number)[2] for number in range(200))
        tokens = sum(len(label) for label in LABELS) * 200
        self.assertAlmostEqual(total / tokens, 0.05, delta=0.01)

    def test_a_line_is_prepared_as_ocrdataset_prepares_it(self):
        import numpy
        from PIL import Image
        from vietocr.tool.translate import process_image, resize

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.fromarray(numpy.random.RandomState(1).randint(0, 255, (40, 900, 3), dtype=numpy.uint8)).save(root / "long.png")
            Image.new("L", (100, 25), 200).save(root / "short.png")
            samples = [("long.png", LABELS[1]), ("short.png", LABELS[0]), ("long.png", LABELS[2])]
            for width in (512, 1024):
                sizes = {"image_height": 32, "image_min_width": 32, "image_max_width": width}
                data = training.LineDataset(root, samples, self.vocab, sizes)
                item = data[0]
                with Image.open(root / "long.png") as image:
                    expected = process_image(image.convert("RGB"), 32, 32, width)
                self.assertTrue(numpy.array_equal(item["img"], expected))
                self.assertEqual(item["img"].shape, (3, 32, resize(900, 40, 32, 32, width)[0]))
                self.assertEqual(item["word"], self.vocab.encode(LABELS[1]))
                buckets = training.width_buckets(root, samples, sizes)
                self.assertEqual(buckets, {resize(900, 40, 32, 32, width)[0]: [0, 2], resize(100, 25, 32, 32, width)[0]: [1]})
            self.assertEqual(len(data), 3)

    def fresh(self, seed: int = 11):
        import torch

        torch.manual_seed(seed)
        settings = training.resolve_settings(self.config, arguments())
        return training.build(self.config, settings)

    def batches(self, count: int) -> list[dict]:
        result = []
        for number in range(count):
            batch = training.collate(self.samples(width=64 + 32 * (number % 2)))
            training.mask_tokens(batch["tgt_input"], 1, number)
            result.append(batch)
        return result

    def same_weights(self, first, second) -> bool:
        import torch

        return all(torch.equal(a, b) for a, b in zip(first.state_dict().values(), second.state_dict().values()))

    def test_optimizer_schedule_and_loss_are_the_trainers(self):
        from torch.optim import AdamW
        from torch.optim.lr_scheduler import OneCycleLR
        from vietocr.optim.labelsmoothingloss import LabelSmoothingLoss

        model, vocab, optimizer, scheduler, criterion = self.fresh()
        self.assertIsInstance(optimizer, AdamW)
        self.assertEqual((optimizer.defaults["betas"], optimizer.defaults["eps"]), ((0.9, 0.98), 1e-09))
        self.assertIsInstance(scheduler, OneCycleLR)
        self.assertEqual(scheduler.total_steps, 4670)
        self.assertAlmostEqual(optimizer.param_groups[0]["max_lr"], 0.0001)
        self.assertAlmostEqual(optimizer.param_groups[0]["lr"], 0.0001 / 25)  # OneCycleLR starts a 25th below the peak
        self.assertIsInstance(criterion, LabelSmoothingLoss)
        self.assertEqual((criterion.smoothing, criterion.padding_idx, criterion.cls), (0.1, vocab.pad, len(vocab)))

    def test_one_step_without_accumulation_is_trainer_step(self):
        import torch

        batch = self.batches(1)[0]
        model, _, optimizer, scheduler, criterion = self.fresh()
        torch.manual_seed(99)
        outcome = training.optimizer_step(model, criterion, optimizer, scheduler, None, [batch], "cpu")

        # vietocr/model/trainer.py, Trainer.step, statement by statement.
        reference, _, ref_optimizer, ref_scheduler, ref_criterion = self.fresh()
        torch.manual_seed(99)
        reference.train()
        outputs = reference(batch["img"], batch["tgt_input"], tgt_key_padding_mask=batch["tgt_padding_mask"])
        outputs = outputs.view(-1, outputs.size(2))
        loss = ref_criterion(outputs, batch["tgt_output"].view(-1))
        ref_optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(reference.parameters(), 1)
        ref_optimizer.step()
        ref_scheduler.step()

        self.assertEqual(outcome["loss"], loss.item())
        self.assertTrue(self.same_weights(model, reference))
        self.assertEqual(optimizer.param_groups[0]["lr"], ref_optimizer.param_groups[0]["lr"])
        self.assertTrue(math.isfinite(outcome["loss"]) and outcome["gradient_norm"] > 0)

    def test_accumulated_passes_make_one_step_on_their_mean_loss(self):
        import torch

        first, second = self.batches(2)
        model, _, optimizer, scheduler, criterion = self.fresh()
        torch.manual_seed(5)
        outcome = training.optimizer_step(model, criterion, optimizer, scheduler, None, [first, second], "cpu", count_gradients=True)

        reference, _, ref_optimizer, ref_scheduler, ref_criterion = self.fresh()
        torch.manual_seed(5)
        reference.train()
        ref_optimizer.zero_grad()
        losses = []
        for batch in (first, second):
            outputs = reference(batch["img"], batch["tgt_input"], tgt_key_padding_mask=batch["tgt_padding_mask"])
            loss = ref_criterion(outputs.view(-1, outputs.size(2)), batch["tgt_output"].view(-1))
            (loss / 2).backward()
            losses.append(loss.item())
        torch.nn.utils.clip_grad_norm_(reference.parameters(), 1)
        ref_optimizer.step()
        ref_scheduler.step()

        self.assertTrue(self.same_weights(model, reference))
        self.assertAlmostEqual(outcome["loss"], sum(losses) / 2)
        self.assertEqual(scheduler.last_epoch, 1)  # two forward passes, one optimizer step
        self.assertEqual(outcome["tensors_with_gradient"], sum(1 for _ in model.parameters()))

    def test_a_restored_run_continues_exactly_like_an_uninterrupted_one(self):
        import io

        import torch

        batches = self.batches(4)
        model, _, optimizer, scheduler, criterion = self.fresh()
        torch.manual_seed(42)
        for batch in batches[:2]:
            training.optimizer_step(model, criterion, optimizer, scheduler, None, [batch], "cpu")
        buffer = io.BytesIO()
        torch.save(training.training_state(2, model, optimizer, scheduler, None, {"steps_done": 2}), buffer)
        for batch in batches[2:]:
            training.optimizer_step(model, criterion, optimizer, scheduler, None, [batch], "cpu")

        resumed, _, res_optimizer, res_scheduler, res_criterion = self.fresh(seed=1234)  # other weights, other random state
        torch.manual_seed(7)
        buffer.seek(0)
        state = torch.load(buffer, weights_only=False)
        training.restore_state(state, resumed, res_optimizer, res_scheduler, None)
        self.assertEqual((state["step"], state["record"]), (2, {"steps_done": 2}))
        for batch in batches[2:]:
            training.optimizer_step(resumed, res_criterion, res_optimizer, res_scheduler, None, [batch], "cpu")

        self.assertTrue(self.same_weights(model, resumed))
        self.assertEqual(res_scheduler.last_epoch, scheduler.last_epoch)
        self.assertEqual(res_optimizer.param_groups[0]["lr"], optimizer.param_groups[0]["lr"])

    def test_training_changes_the_weights_and_the_seed_makes_it_repeatable(self):
        import torch

        batch = self.batches(1)[0]
        outcomes = []
        for _ in range(2):
            training.seed_everything(20261201)
            model, _, optimizer, scheduler, criterion = training.build(self.config, training.resolve_settings(self.config, arguments()))
            before = {name: value.clone() for name, value in model.state_dict().items()}
            outcome = training.optimizer_step(model, criterion, optimizer, scheduler, None, [batch], "cpu")
            changed = sum(not torch.equal(before[name], value) for name, value in model.named_parameters())
            outcomes.append((outcome["loss"], outcome["gradient_norm"], changed, model))
        self.assertEqual(outcomes[0][:3], outcomes[1][:3])
        self.assertTrue(self.same_weights(outcomes[0][3], outcomes[1][3]))
        self.assertGreater(outcomes[0][2], 0)

    def buffers(self, model) -> dict:
        parameters = {name for name, _ in model.named_parameters()}
        return {name: value.clone() for name, value in model.state_dict().items() if name not in parameters}

    def test_batch_norm_statistics_are_updated_as_in_the_pinned_trainer_by_default(self):
        import torch

        model, _, optimizer, scheduler, criterion = self.fresh()
        before = self.buffers(model)
        training.optimizer_step(model, criterion, optimizer, scheduler, None, self.batches(1), "cpu")
        after = self.buffers(model)
        moved = [name for name in before if name.endswith(("running_mean", "running_var")) and not torch.equal(before[name], after[name])]
        self.assertEqual(len(moved), sum(name.endswith(("running_mean", "running_var")) for name in before))
        self.assertGreater(len(moved), 0)

    def test_frozen_statistics_stay_while_scale_and_shift_are_trained(self):
        import torch
        from torch.nn.modules.batchnorm import _BatchNorm

        model, _, optimizer, scheduler, criterion = self.fresh()
        before, weights = self.buffers(model), {name: value.clone() for name, value in model.named_parameters()}
        outcome = training.optimizer_step(model, criterion, optimizer, scheduler, None, self.batches(1), "cpu",
                                          count_gradients=True, freeze_statistics=True)  # fmt: skip
        after = self.buffers(model)
        self.assertTrue(all(torch.equal(before[name], after[name]) for name in before))
        layers = [module for module in model.modules() if isinstance(module, _BatchNorm)]
        self.assertEqual(len(layers), 16)  # VGG19-bn
        self.assertTrue(all(not layer.training for layer in layers))
        self.assertTrue(model.transformer.training)  # the rest trains as usual, dropout included
        self.assertTrue(all(layer.weight.grad is not None and bool(layer.weight.grad.abs().sum() > 0) for layer in layers))
        self.assertEqual(outcome["tensors_with_gradient"], sum(1 for _ in model.parameters()))
        self.assertTrue(any(not torch.equal(weights[name], value) for name, value in model.named_parameters()))

    def test_a_frozen_layer_normalises_with_the_stored_statistics_not_with_the_batch(self):
        import torch
        from torch.nn import functional
        from torch.nn.modules.batchnorm import _BatchNorm

        model, _, _, _, _ = self.fresh()
        layer = next(module for module in model.modules() if isinstance(module, _BatchNorm))
        with torch.no_grad():  # statistics that differ from those of any batch
            layer.running_mean.uniform_(-1.0, 1.0)
            layer.running_var.uniform_(0.5, 2.0)
        mean, variance = layer.running_mean.clone(), layer.running_var.clone()
        batch = torch.randn(4, layer.num_features, 8, 20) * 3 + 2

        model.train()
        self.assertEqual(training.freeze_batch_norm_statistics(model), 16)
        frozen = layer(batch)
        stored = functional.batch_norm(batch, mean, variance, layer.weight, layer.bias, False, 0.0, layer.eps)
        own = functional.batch_norm(batch, None, None, layer.weight, layer.bias, True, 0.0, layer.eps)
        self.assertTrue(torch.equal(frozen, stored))
        self.assertFalse(torch.allclose(frozen, own, atol=1e-3))
        self.assertTrue(torch.equal(layer.running_mean, mean) and torch.equal(layer.running_var, variance))

        model.train()  # the pinned trainer's way, for contrast: the batch decides, and the stored values move
        updated = layer(batch)
        self.assertTrue(torch.allclose(updated, own, atol=1e-5))
        self.assertFalse(torch.equal(layer.running_mean, mean))

    def test_frozen_statistics_survive_many_steps_while_gamma_and_beta_move(self):
        import torch
        from torch.nn.modules.batchnorm import _BatchNorm

        model, _, optimizer, scheduler, criterion = self.fresh()
        original = {name: value.clone() for name, value in model.state_dict().items()}
        self.assertTrue(training.batch_norm_report(model, original)["running_statistics_unchanged"])
        for group in ([b] for b in self.batches(4)):
            training.optimizer_step(model, criterion, optimizer, scheduler, None, group, "cpu", freeze_statistics=True)
        report = training.batch_norm_report(model, original)
        self.assertEqual((report["layers"], report["affine_tensors"]), (16, 32))
        self.assertEqual(report["statistics_tensors_changed"], 0)  # mean, variance and the batch counter of all 16 layers
        self.assertTrue(report["running_statistics_unchanged"] and report["affine_trainable"])
        self.assertEqual(report["affine_tensors_changed"], 32)  # every gamma and every beta was updated
        # Nothing else is frozen: every parameter is trainable and the convolutions moved too.
        self.assertTrue(all(parameter.requires_grad for parameter in model.parameters()))
        layers = [name for name, module in model.named_modules() if isinstance(module, _BatchNorm)]
        others = [name for name, _ in model.named_parameters() if name.rsplit(".", 1)[0] not in layers]
        self.assertTrue(all(not torch.equal(original[name], model.state_dict()[name]) for name in others if name.startswith("cnn.")))
        self.assertTrue(any(not torch.equal(original[name], model.state_dict()[name]) for name in others if name.startswith("transformer.")))

    def test_the_report_sees_statistics_that_were_updated(self):
        model, _, optimizer, scheduler, criterion = self.fresh()
        original = {name: value.clone() for name, value in model.state_dict().items()}
        training.optimizer_step(model, criterion, optimizer, scheduler, None, self.batches(1), "cpu")
        report = training.batch_norm_report(model, original)
        self.assertFalse(report["running_statistics_unchanged"])
        self.assertEqual(report["statistics_tensors_changed"], 48)  # mean, variance and counter of 16 layers

    def probe_settings(self, **changes) -> dict:
        return {"device": "cpu", "experiment": "test", "image_max_width": 512, "physical_batch_size": 2, "accumulation_steps": 2,
                "effective_batch_size": 4, "mixed_precision": False, "batch_norm_statistics": "frozen", **changes}  # fmt: skip

    def test_the_memory_probe_runs_the_worst_batches_and_keeps_nothing(self):
        import torch

        model, _, optimizer, scheduler, criterion = self.fresh()
        data = self.samples() + self.samples(width=64)
        samples = [(f"{i}.png", label) for i, label in enumerate(LABELS + LABELS)]
        buckets = {96: [0, 1, 2, 3], 64: [4, 5, 6, 7]}
        result = training.probe_memory(model, criterion, optimizer, scheduler, None, data, samples, buckets, self.probe_settings())
        self.assertEqual((result["optimizer_steps"], len(result["losses"]), result["out_of_memory"]), (training.PROBE_STEPS, 3, False))
        self.assertTrue(result["loss_finite"])
        self.assertEqual((result["widest_width"], result["longest_label_in_probe"]), (96, max(map(len, LABELS))))
        self.assertEqual((result["physical_batch_size"], result["accumulation_steps"], result["device"]), (2, 2, "cpu"))
        self.assertNotIn("gpu", result)  # filled in on a CUDA device only
        self.assertGreater(result["process_peak_rss_mb"], 0)
        self.assertEqual(result["torch"], torch.__version__)

    def test_running_out_of_memory_is_a_result_and_any_other_error_is_an_error(self):
        from unittest import mock

        model, _, optimizer, scheduler, criterion = self.fresh()
        data, samples, buckets = self.samples(), [(f"{i}.png", label) for i, label in enumerate(LABELS)], {96: [0, 1, 2, 3]}
        with mock.patch.object(training, "optimizer_step", side_effect=RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")):
            result = training.probe_memory(model, criterion, optimizer, scheduler, None, data, samples, buckets, self.probe_settings())
        self.assertEqual((result["out_of_memory"], result["optimizer_steps"], result["loss_finite"]), (True, 0, False))
        with mock.patch.object(training, "optimizer_step", side_effect=RuntimeError("something else")):
            with self.assertRaises(RuntimeError):
                training.probe_memory(model, criterion, optimizer, scheduler, None, data, samples, buckets, self.probe_settings())

    def test_the_mixed_precision_check_compares_one_batch_both_ways(self):
        import warnings

        model, _, _, _, criterion = self.fresh()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # without CUDA autocast switches itself off: both losses are single precision
            check = training.amp_loss_check(model, criterion, self.batches(1)[0], "cpu")
        self.assertEqual(set(check), {"fp32_loss", "amp_loss", "absolute_difference", "within_tolerance"})
        self.assertEqual((check["absolute_difference"], check["within_tolerance"]), (0.0, True))
        self.assertFalse(model.training)  # read without dropout
        self.assertEqual(training.AMP_LOSS_TOLERANCE, 0.01)

    @unittest.skipUnless(run_vietocr.WEIGHTS_PATH.is_file(), "needs the pretrained weights")
    def test_the_pretrained_checkpoint_loads_completely(self):
        model, _, _, _, _ = self.fresh()
        loaded = training.load_pretrained(model, run_vietocr.WEIGHTS_PATH, "cpu")
        self.assertEqual((loaded["missing"], loaded["shape_mismatch"]), (0, 0))
        self.assertEqual(loaded["identical_to_checkpoint"], loaded["parameter_tensors"])
        self.assertTrue(loaded["loaded"])
        self.assertEqual(sum(value.numel() for value in model.parameters()), 37_650_217)


if __name__ == "__main__":
    unittest.main()

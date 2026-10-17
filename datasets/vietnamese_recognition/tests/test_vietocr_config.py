"""The width-experiment configs: derived from the pinned pretrained one, equal but for the width."""

import math
import unittest

import _paths  # noqa: F401
import build_vietocr_config as builder
import dataset_common as dataset
import yaml

from run_vietocr import VIETOCR_COMMIT, WEIGHTS_PATH


def flatten(value, prefix=""):
    if not isinstance(value, dict):
        return {prefix: value}
    return {k: v for key, child in value.items() for k, v in flatten(child, f"{prefix}.{key}".strip(".")).items()}


class Configs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pretrained = builder.pretrained_config()
        cls.configs = {
            name: yaml.safe_load(builder.config_path(name).read_text(encoding="utf-8")) for name in builder.EXPERIMENTS
        }

    def test_files_are_what_the_builder_produces(self):
        for name in builder.EXPERIMENTS:
            self.assertEqual(builder.config_path(name).read_text(encoding="utf-8"), builder.render_config(name))
            self.assertEqual(self.configs[name], builder.fine_tuning_config(name))
        self.assertEqual(builder.main(["--check"]), 0)

    def test_two_experiments_512_and_1024(self):
        self.assertEqual(
            {name: config["dataset"]["image_max_width"] for name, config in self.configs.items()},
            {"exp_a_width512": 512, "exp_b_width1024": 1024},
        )
        self.assertEqual(self.pretrained["dataset"]["image_max_width"], 512)

    def test_the_experiments_differ_in_width_and_output_paths_only(self):
        first, second = (flatten(self.configs[name]) for name in ("exp_a_width512", "exp_b_width1024"))
        different = {key for key in first.keys() | second.keys() if first.get(key) != second.get(key)}
        self.assertEqual(
            different,
            {"dataset.image_max_width", "weights", "trainer.export", "trainer.checkpoint", "trainer.log", "experiment.name"},
        )
        # In particular: same data, seed, starting weights, learning rate, batch and budget.
        for key in ("dataset.name", "dataset.train_annotation", "dataset.valid_annotation", "experiment.seed",
                    "pretrain", "optimizer.max_lr", "optimizer.pct_start", "trainer.batch_size", "trainer.iters",
                    "trainer.valid_every", "aug.image_aug", "aug.masked_language_model", "vocab"):  # fmt: skip
            self.assertEqual(first[key], second[key], key)

    def test_they_live_outside_the_vietocr_checkout(self):
        for name in builder.EXPERIMENTS:
            self.assertNotIn(dataset.VIETOCR_DIR, builder.config_path(name).parents)
            self.assertEqual(builder.config_path(name).parent, dataset.VIETOCR_CONFIG_DIR)
        self.assertFalse((dataset.VIETOCR_CONFIG_DIR / "vgg_transformer_vi_admin.yml").exists())

    def test_vocabulary_and_architecture_are_the_pretrained_ones(self):
        for config in self.configs.values():
            # Another vocabulary would change the output layer and orphan the checkpoint.
            self.assertEqual(config["vocab"], self.pretrained["vocab"])
            for key in ("backbone", "seq_modeling", "transformer"):
                self.assertEqual(config[key], self.pretrained[key], key)
            for key in ("ss", "ks", "hidden"):
                self.assertEqual(config["cnn"][key], self.pretrained["cnn"][key], key)
        self.assertNotIn("vocab", builder.OVERRIDES)

    def test_only_documented_settings_differ_from_pretrained(self):
        before = flatten(self.pretrained)
        for name, config in self.configs.items():
            after = flatten(config)
            changed = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
            allowed = set(flatten(builder.OVERRIDES)) | set(flatten(builder.experiment_overrides(name)))
            self.assertLessEqual(changed, allowed, name)

    def test_they_start_from_the_checkpoint_the_bakeoff_evaluated(self):
        for config in self.configs.values():
            self.assertEqual(dataset.REPO_ROOT / config["pretrain"], WEIGHTS_PATH)
        self.assertEqual(len(VIETOCR_COMMIT), 40)

    def test_training_uses_the_mix_and_validation_is_real(self):
        for config in self.configs.values():
            data = config["dataset"]
            self.assertEqual(dataset.REPO_ROOT / data["data_root"], dataset.DATASET_DIR)
            self.assertEqual(data["train_annotation"], "manifests/vietocr/train_mix_annotation.txt")
            self.assertEqual(data["valid_annotation"], "manifests/vietocr/real_val_annotation.txt")

    def test_selection_is_on_real_validation_never_on_the_blind_test(self):
        for config in self.configs.values():
            experiment = config["experiment"]
            self.assertEqual(experiment["selection_split"], dataset.REAL_VAL)
            self.assertEqual((experiment["selection_metric"], experiment["selection_tiebreak"]), ("cer_nfc", "wer_nfc"))
            self.assertFalse(experiment["blind_test_used_for_selection"])
            self.assertNotIn(dataset.BLIND_TEST, experiment["diagnostic_splits"])
            self.assertNotIn(dataset.BLIND_TEST, experiment["selection_split"])
            text = yaml.safe_dump({k: v for k, v in config.items() if k != "experiment"})
            self.assertNotIn("blind", text)  # no path of the run points at the blind test

    def test_the_files_a_run_would_read_hold_no_evaluation_line(self):
        for config in self.configs.values():
            data = config["dataset"]
            root = dataset.REPO_ROOT / data["data_root"]
            # Quarantined labels are a separate refusal, see test_line_endings_and_quarantine.
            self.assertEqual(dataset.evaluation_line_problems(root / data["train_annotation"], root / data["valid_annotation"], root), [])
        check = (dataset.DATASET_DIR / "check_vietocr_config.py").read_text(encoding="utf-8")
        self.assertIn("dataset.training_data_problems(", check)  # the readiness check applies the same rule

    def test_the_decoder_runs_128_steps_in_both_experiments(self):
        for name, config in self.configs.items():
            self.assertEqual(config["decoder_max_seq_length"], 128, name)
            # A project key at the top level; the blocks VietOCR reads carry no such setting.
            self.assertNotIn("decoder_max_seq_length", config["predictor"])
            self.assertNotIn("decoder_max_seq_length", config["transformer"])
            # One position per token the decoder is shown: the start token and each step but the last.
            self.assertLessEqual(config["decoder_max_seq_length"] + 1, config["transformer"]["max_seq_length"])
        self.assertNotIn("decoder_max_seq_length", self.pretrained)
        self.assertEqual(self.pretrained["transformer"]["max_seq_length"], 1024)

    def test_supported_label_length_follows_both_capacities(self):
        def supported(decoder: int, transformer: int) -> int:
            return builder.supported_label_characters({"decoder_max_seq_length": decoder, "transformer": {"max_seq_length": transformer}})

        self.assertEqual(supported(160, 1024), 160)  # the decoder is what binds
        self.assertEqual(supported(128, 1024), 128)
        self.assertEqual(supported(2000, 1024), 1022)  # then the transformer: start token + label + end token
        for name, config in self.configs.items():
            self.assertEqual(builder.supported_label_characters(config), 128, name)
            self.assertEqual(builder.supported_label_characters({**config, "decoder_max_seq_length": 160}), 160, name)

    def test_every_label_a_run_would_read_fits(self):
        limit = builder.label_limit()["characters"]
        for config in self.configs.values():
            data = config["dataset"]
            root = dataset.REPO_ROOT / data["data_root"]
            for key in ("train_annotation", "valid_annotation"):
                path = root / data[key]
                if not path.is_file():
                    continue  # built on the machine that holds the images
                longest = max((len(line.split("\t")[1]) for line in path.read_text(encoding="utf-8").splitlines()), default=0)
                self.assertLessEqual(longest, limit, key)

    def test_the_limit_the_audit_uses_is_read_from_the_files(self):
        limit = builder.label_limit()
        self.assertEqual((limit["characters"], limit["decoder_max_seq_length"], limit["transformer_max_seq_length"]), (128, 128, 1024))
        self.assertIn(limit["config"], {f"{name}.yml" for name in builder.EXPERIMENTS})

    def test_image_width_fits_the_positional_encoding(self):
        for config in self.configs.values():
            data = config["dataset"]
            self.assertEqual(data["image_height"], 32)
            # The VGG backbone halves the height four times and the width twice,
            # and the feature map is flattened: (H / 16) * (W / 4) positions.
            positions = (data["image_height"] // 16) * math.ceil(data["image_max_width"] / 4)
            self.assertLessEqual(positions, config["transformer"]["max_seq_length"])

    def test_training_settings(self):
        for config in self.configs.values():
            trainer = config["trainer"]
            self.assertGreater(trainer["iters"], trainer["valid_every"])
            self.assertLess(config["optimizer"]["max_lr"], self.pretrained["optimizer"]["max_lr"])
            for key in ("export", "checkpoint", "log"):
                self.assertTrue(trainer[key].startswith("models/"), key)  # outside git
            self.assertFalse(config["cnn"]["pretrained"])
            self.assertFalse(config["aug"]["image_aug"])


if __name__ == "__main__":
    unittest.main()

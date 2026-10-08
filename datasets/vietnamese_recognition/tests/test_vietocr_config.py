"""The fine-tuning config: derived from the pinned pretrained one, nothing else changed."""

import math
import unittest

import _paths  # noqa: F401
import build_vietocr_config as builder
import dataset_common as dataset
import yaml

from run_vietocr import VIETOCR_COMMIT, WEIGHTS_PATH


class Config(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pretrained = builder.pretrained_config()
        cls.config = yaml.safe_load(builder.CONFIG.read_text(encoding="utf-8"))

    def test_file_is_what_the_builder_produces(self):
        self.assertEqual(builder.CONFIG.read_text(encoding="utf-8"), builder.render_config())
        self.assertEqual(self.config, builder.fine_tuning_config())
        self.assertEqual(builder.main(["--check"]), 0)

    def test_it_lives_outside_the_vietocr_checkout(self):
        self.assertNotIn(dataset.VIETOCR_DIR, builder.CONFIG.parents)
        self.assertEqual(builder.CONFIG.parent, dataset.REPO_ROOT / "configs" / "vietnamese" / "vietocr")

    def test_vocabulary_is_the_pretrained_one(self):
        # Another vocabulary would change the output layer and orphan the checkpoint.
        self.assertEqual(self.config["vocab"], self.pretrained["vocab"])
        self.assertNotIn("vocab", builder.OVERRIDES)

    def test_architecture_is_the_pretrained_one(self):
        for key in ("backbone", "seq_modeling", "transformer"):
            self.assertEqual(self.config[key], self.pretrained[key], key)
        for key in ("ss", "ks", "hidden"):
            self.assertEqual(self.config["cnn"][key], self.pretrained["cnn"][key], key)
        self.assertEqual(self.config["backbone"], "vgg19_bn")
        self.assertEqual(self.config["seq_modeling"], "transformer")

    def test_only_documented_settings_differ(self):
        def flatten(value, prefix=""):
            if not isinstance(value, dict):
                return {prefix: value}
            return {k: v for key, child in value.items() for k, v in flatten(child, f"{prefix}.{key}".strip(".")).items()}

        before, after = flatten(self.pretrained), flatten(self.config)
        changed = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
        self.assertLessEqual(changed, set(flatten(builder.OVERRIDES)))

    def test_it_starts_from_the_checkpoint_the_bakeoff_evaluated(self):
        self.assertEqual(dataset.REPO_ROOT / self.config["pretrain"], WEIGHTS_PATH)
        self.assertEqual(self.pretrained["pretrain"], "https://vocr.vn/data/vietocr/vgg_transformer.pth")
        self.assertEqual(len(VIETOCR_COMMIT), 40)

    def test_dataset_paths_point_at_the_training_and_validation_annotations(self):
        data = self.config["dataset"]
        self.assertEqual(dataset.REPO_ROOT / data["data_root"], dataset.DATASET_DIR)
        self.assertEqual(data["train_annotation"], "manifests/vietocr/train_annotation.txt")
        self.assertEqual(data["valid_annotation"], "manifests/vietocr/val_annotation.txt")
        self.assertNotIn("test", data["train_annotation"] + data["valid_annotation"])

    def test_image_width_fits_the_positional_encoding(self):
        data = self.config["dataset"]
        self.assertEqual(data["image_height"], 32)
        self.assertGreaterEqual(data["image_max_width"], 512)
        # The VGG backbone halves the height four times and the width twice,
        # and the feature map is flattened: (H / 16) * (W / 4) positions.
        positions = (data["image_height"] // 16) * math.ceil(data["image_max_width"] / 4)
        self.assertLessEqual(positions, self.config["transformer"]["max_seq_length"])

    def test_training_settings(self):
        trainer = self.config["trainer"]
        self.assertGreater(trainer["batch_size"], 0)
        self.assertGreater(trainer["iters"], trainer["valid_every"])
        self.assertLess(self.config["optimizer"]["max_lr"], self.pretrained["optimizer"]["max_lr"])
        for key in ("export", "checkpoint", "log"):
            self.assertTrue(trainer[key].startswith("models/"), key)  # outside git
        self.assertFalse(self.config["cnn"]["pretrained"])
        self.assertFalse(self.config["aug"]["image_aug"])


if __name__ == "__main__":
    unittest.main()

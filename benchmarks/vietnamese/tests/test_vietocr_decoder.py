"""How long a line the VietOCR runner lets the decoder write, and where that number comes from.

The tests that run the network need PyTorch and are skipped elsewhere; run this
file in the VietOCR environment to include them:

    .venv-vietocr/bin/python -m unittest discover -s benchmarks/vietnamese/tests -p "test_vietocr_decoder.py"
"""

import importlib.util
import inspect
import json
import re
import subprocess
import sys
import tempfile
import types
import unittest
import unittest.mock
from pathlib import Path

import _paths
import bakeoff_common as bakeoff
import run_vietocr
import yaml

# The pinned checkout must stay free of bytecode files, as in the runner itself.
sys.dont_write_bytecode = True

HAS_TORCH = importlib.util.find_spec("torch") is not None
NEEDS_TORCH = "needs PyTorch: run this file with .venv-vietocr/bin/python"
CONFIG_DIR = _paths.REPO_ROOT / "configs" / "vietnamese" / "vietocr"
EXPERIMENTS = ("exp_a_width512.yml", "exp_b_width1024.yml")
SENTENCE = "Căn cứ Nghị định số 15/2024/NĐ-CP ngày 05 tháng 02 năm 2025 của Chính phủ quy định chức năng, nhiệm vụ; "
LABEL_129 = (SENTENCE * 2)[:128] + "."
LABEL_160 = (SENTENCE * 2)[:159] + "."


def experiment(name: str) -> dict:
    return yaml.safe_load((CONFIG_DIR / name).read_text(encoding="utf-8"))


def vocabulary():
    """VietOCR's own ``Vocab`` over the configured characters, loaded without the rest of the package."""
    spec = importlib.util.spec_from_file_location("pinned_vietocr_vocab", run_vietocr.VIETOCR_DIR / "vietocr" / "model" / "vocab.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Vocab(experiment(EXPERIMENTS[0])["vocab"])


def use_pinned_checkout() -> None:
    if str(run_vietocr.VIETOCR_DIR) not in sys.path:
        sys.path.insert(0, str(run_vietocr.VIETOCR_DIR))


class WhereTheLimitComesFrom(unittest.TestCase):
    def test_both_experiment_configs_say_128(self):
        for name in EXPERIMENTS:
            config = experiment(name)
            self.assertEqual(config[run_vietocr.DECODER_KEY], 128, name)
            # The same number as VietOCR's default, but taken from the file.
            self.assertEqual(run_vietocr.decoder_limit(config), (128, "config"), name)
            # One position per token the decoder has seen: the start token and every step but the last.
            self.assertLessEqual(128 + 1, config["transformer"]["max_seq_length"])

    def test_the_number_in_a_config_is_the_number_used(self):
        for steps in (96, 128, 160, 200):
            self.assertEqual(run_vietocr.decoder_limit({run_vietocr.DECODER_KEY: steps}), (steps, "config"))

    def test_the_stock_configuration_keeps_what_the_bakeoff_ran_with(self):
        self.assertEqual(run_vietocr.STOCK_DECODER_MAX_SEQ_LENGTH, 128)
        self.assertEqual(run_vietocr.decoder_limit({}), (128, "VietOCR default"))

    def test_a_number_on_the_command_line_wins(self):
        self.assertEqual(run_vietocr.decoder_limit({run_vietocr.DECODER_KEY: 160}, 128), (128, "command line"))
        self.assertEqual(run_vietocr.decoder_limit({}, 140), (140, "command line"))

    def test_text_that_fits_with_its_end_token(self):
        self.assertEqual(run_vietocr.decodable_characters(128), 128)
        self.assertEqual(run_vietocr.decodable_characters(160), 160)
        # A 129-character line needs more than the configured 128 steps to be closed.
        self.assertLess(run_vietocr.decodable_characters(128), len(LABEL_129))
        self.assertGreaterEqual(run_vietocr.decodable_characters(160), len(LABEL_129))

    def test_other_runs_never_replace_the_stock_predictions(self):
        for arguments in (["--config", str(CONFIG_DIR / EXPERIMENTS[0])], ["--decoder-max-seq-length", "160"]):
            with self.assertRaises(SystemExit) as refusal:
                run_vietocr.main(arguments)
            self.assertIn("--output", str(refusal.exception))
        with self.assertRaises(SystemExit):
            run_vietocr.main(["--decoder-max-seq-length", "0", "--output", "unused.jsonl"])

    def test_the_runner_never_leaves_the_number_to_a_default(self):
        source = (_paths.BAKEOFF_DIR / "run_vietocr.py").read_text(encoding="utf-8")
        calls = re.findall(r"\b(translate(?:_beam_search)?)\((.*)\)", source)
        self.assertEqual(sorted(name for name, _ in calls), ["translate", "translate_beam_search"])
        for name, arguments in calls:
            self.assertIn("max_seq_length=max_seq_length", arguments, name)
        self.assertIsNone(re.search(r"\bpredictor\.predict\(", source))  # it would decode with the default

    def test_nothing_of_vietocr_is_patched(self):
        for path in (_paths.BAKEOFF_DIR / "run_vietocr.py", _paths.REPO_ROOT / "datasets" / "vietnamese_recognition" / "check_vietocr_config.py"):
            source = path.read_text(encoding="utf-8")
            for forbidden in ("__defaults__", "setattr(", "monkeypatch", "mock.patch"):
                self.assertNotIn(forbidden, source, path.name)
            self.assertIsNone(re.search(r"^\s*(vietocr|translate)\.[\w.]+\s*=", source, re.MULTILINE), path.name)


class PinnedCheckout(unittest.TestCase):
    def git(self, *arguments: str) -> str:
        return subprocess.run(["git", "-C", str(run_vietocr.VIETOCR_DIR), *arguments], capture_output=True, text=True, check=True).stdout

    def test_third_party_vietocr_is_untouched(self):
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), run_vietocr.VIETOCR_COMMIT)
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(self.git("diff", "HEAD", "--stat"), "")

    def test_its_decoder_default_is_still_128(self):
        source = (run_vietocr.VIETOCR_DIR / "vietocr" / "tool" / "translate.py").read_text(encoding="utf-8")
        self.assertIn("def translate(img, model, max_seq_length=128, sos_token=1, eos_token=2):", source)
        predictor = (run_vietocr.VIETOCR_DIR / "vietocr" / "tool" / "predictor.py").read_text(encoding="utf-8")
        self.assertIn("s, prob = translate(img, self.model)", predictor)  # which is why the runner does not use it


class LongLabels(unittest.TestCase):
    def test_a_129_character_label_encodes(self):
        vocab = vocabulary()
        self.assertEqual((len(LABEL_129), len(LABEL_160)), (129, 160))
        encoded = vocab.encode(LABEL_129)
        self.assertEqual(len(encoded), 131)  # the label between a start and an end token
        self.assertEqual((encoded[0], encoded[-1]), (vocab.go, vocab.eos))
        self.assertEqual(vocab.decode(encoded), LABEL_129)
        self.assertEqual(vocab.decode(vocab.encode(LABEL_160)), LABEL_160)

    def test_encoding_has_no_length_limit_of_its_own(self):
        vocab = vocabulary()
        self.assertEqual(len(vocab.encode("a" * 1000)), 1002)


class Endless:
    """Stands in for the network: writes ``character`` at every step, and the end token after ``length`` steps if given."""

    def __init__(self, classes: int, character: int, end_token: int, length: int | None = None) -> None:
        self.classes, self.character, self.end_token, self.length = classes, character, end_token, length
        self.transformer = self

    def eval(self) -> None:
        pass

    def cnn(self, image):
        return image

    def forward_encoder(self, source):
        return source

    def forward_decoder(self, target, memory):
        import torch

        steps, batch = target.shape
        output = torch.zeros(batch, steps, self.classes)
        token = self.end_token if self.length is not None and steps > self.length else self.character
        output[:, -1, token] = 50.0
        return output, memory


@unittest.skipUnless(HAS_TORCH, NEEDS_TORCH)
class DecodingSteps(unittest.TestCase):
    """The project's ``recognise`` driving VietOCR's real ``translate`` loop."""

    def setUp(self):
        use_pinned_checkout()
        from PIL import Image

        self.vocab = vocabulary()
        self.image = Image.new("RGB", (320, 32), "white")
        self.character = self.vocab.c2i["a"]

    def read(self, max_seq_length: int, length: int | None = None):
        config = {"device": "cpu", "predictor": {"beamsearch": False},
                  "dataset": {"image_height": 32, "image_min_width": 32, "image_max_width": 512}}  # fmt: skip
        model = Endless(len(self.vocab), self.character, self.vocab.eos, length)
        predictor = types.SimpleNamespace(config=config, model=model, vocab=self.vocab)
        text, _, _, hit_limit = run_vietocr.recognise(predictor, self.image, max_seq_length)
        return len(text), hit_limit

    def test_the_number_given_is_the_number_of_steps(self):
        # A network that never ends writes one token per step: steps 0 .. max_seq_length.
        self.assertEqual(self.read(128), (129, True))
        self.assertEqual(self.read(160), (161, True))
        self.assertEqual(self.read(5), (6, True))

    def test_with_160_steps_a_129_character_line_is_read_to_its_end(self):
        self.assertEqual(self.read(160, length=129), (129, False))
        # With VietOCR's default the same line uses up every step and gets no end token.
        self.assertEqual(self.read(128, length=129), (129, True))
        self.assertEqual(self.read(128, length=130), (129, True))  # and one character more is lost

    def test_the_longest_text_that_still_ends(self):
        for steps in (128, 160):
            fits = run_vietocr.decodable_characters(steps)
            self.assertEqual(self.read(steps, length=fits), (fits, False))
            self.assertEqual(self.read(steps, length=fits + 1), (fits + 1, True))

    def test_vietocr_itself_still_defaults_to_128(self):
        from vietocr.tool import translate as module

        self.assertEqual(inspect.signature(module.translate).parameters["max_seq_length"].default, 128)
        self.assertEqual(Path(inspect.getsourcefile(module)).resolve().parents[2], run_vietocr.VIETOCR_DIR.resolve())


@unittest.skipUnless(HAS_TORCH, NEEDS_TORCH)
class TrainingCollator(unittest.TestCase):
    """VietOCR's own collator and network take a long label as they take any other."""

    @classmethod
    def setUpClass(cls):
        use_pinned_checkout()
        # The module also imports what only its LMDB reader needs; the collator needs none of it.
        absent = {name: types.ModuleType(name) for name in ("lmdb", "six", "cv2") if importlib.util.find_spec(name) is None}
        with unittest.mock.patch.dict(sys.modules, absent):
            from vietocr.loader.dataloader import Collator
        cls.Collator = Collator
        cls.vocab = vocabulary()

    def batch(self, *labels: str) -> list[dict]:
        import numpy

        return [{"img": numpy.zeros((3, 32, 320), dtype=numpy.float32), "word": self.vocab.encode(label), "img_path": f"{index}.png"}
                for index, label in enumerate(labels)]  # fmt: skip

    def test_a_129_character_label_goes_through_whole(self):
        collated = self.Collator(masked_language_model=False)(self.batch(LABEL_129, "Số: 15/2024/NĐ-CP"))
        encoded = self.vocab.encode(LABEL_129)
        self.assertEqual(tuple(collated["tgt_input"].shape), (131, 2))  # time first
        self.assertEqual(collated["tgt_input"][:, 0].tolist(), encoded)
        self.assertEqual(tuple(collated["tgt_output"].shape), (2, 131))
        self.assertEqual(collated["tgt_output"][0, :130].tolist(), encoded[1:])
        self.assertEqual(tuple(collated["tgt_padding_mask"].shape), (2, 131))
        self.assertFalse(collated["tgt_padding_mask"][0, :130].any().item())  # none of it is treated as padding
        self.assertTrue(collated["tgt_padding_mask"][1, 30:].all().item())  # the short label is padded instead

    def test_so_does_one_at_the_configured_limit_with_masking_on(self):
        collated = self.Collator(masked_language_model=True)(self.batch(LABEL_160, LABEL_129))
        self.assertEqual(tuple(collated["tgt_input"].shape), (162, 2))
        self.assertEqual((collated["tgt_input"][0, 0].item(), collated["tgt_input"][161, 0].item()), (self.vocab.go, self.vocab.eos))

    def test_the_network_accepts_such_targets(self):
        import torch
        from vietocr.tool.translate import build_model

        config = experiment(EXPERIMENTS[0])
        config["device"] = "cpu"
        model, vocab = build_model(config)  # untrained weights: only the shapes matter here
        model.eval()
        collated = self.Collator(masked_language_model=False)(self.batch(LABEL_160, LABEL_129))
        with torch.no_grad():  # a forward pass; nothing is trained
            output = model(collated["img"], collated["tgt_input"], tgt_key_padding_mask=collated["tgt_padding_mask"])
        self.assertEqual(tuple(output.shape), (2, 162, len(vocab)))
        self.assertTrue(torch.isfinite(output).all().item())


@unittest.skipUnless(HAS_TORCH and run_vietocr.WEIGHTS_PATH.is_file(), "needs PyTorch and the pretrained weights")
class RunnerEndToEnd(unittest.TestCase):
    """The runner as it is started from the command line, on one blank crop."""

    def setUp(self):
        from PIL import Image

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        Image.new("RGB", (200, 30), "white").save(self.root / "blank.png")
        row = {"id": "blank", "crop_path": "blank.png", "crop_sha256": bakeoff.sha256_file(self.root / "blank.png"),
               "crop_width": 200, "crop_height": 30}  # fmt: skip
        bakeoff.write_jsonl(self.root / "inputs.jsonl", [row])

    def run_with(self, *arguments: str) -> tuple[dict, dict]:
        import contextlib
        import io

        output = self.root / "predictions.jsonl"
        with contextlib.redirect_stdout(io.StringIO()):
            status = run_vietocr.main(["--manifest", str(self.root / "inputs.jsonl"), "--output", str(output), *arguments])
        self.assertEqual(status, 0)
        metadata = json.loads(output.with_suffix(".meta.json").read_text(encoding="utf-8"))
        return bakeoff.load_predictions(output)["blank"], metadata

    def test_a_project_config_sets_the_number_of_steps(self):
        for name, width in zip(EXPERIMENTS, (512, 1024)):
            row, metadata = self.run_with("--config", str(CONFIG_DIR / name))
            self.assertEqual((metadata["decoder_max_seq_length"], metadata["decoder_max_seq_length_source"]), (128, "config"))
            self.assertEqual((metadata["project_config"], metadata["image_max_width"]), (name, width))
            self.assertEqual(metadata["longest_text_with_end_token"], 128)
            self.assertIn(row["hit_decoder_limit"], (True, False))
            self.assertEqual(metadata["predictions_at_decoder_limit"], int(row["hit_decoder_limit"]))

    def test_another_number_in_the_config_is_followed(self):
        # The same config with 160 steps: the runner takes what the file says, whatever it says.
        config = experiment(EXPERIMENTS[0])
        config[run_vietocr.DECODER_KEY] = 160
        changed = self.root / "longer_decoder.yml"
        changed.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
        _, metadata = self.run_with("--config", str(changed))
        self.assertEqual((metadata["decoder_max_seq_length"], metadata["decoder_max_seq_length_source"]), (160, "config"))
        self.assertEqual((metadata["project_config"], metadata["longest_text_with_end_token"]), ("longer_decoder.yml", 160))

    def test_a_config_without_the_setting_is_refused(self):
        config = experiment(EXPERIMENTS[0])
        del config[run_vietocr.DECODER_KEY]
        incomplete = self.root / "incomplete.yml"
        incomplete.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
        with self.assertRaises(SystemExit) as refusal:
            self.run_with("--config", str(incomplete))
        self.assertIn("sets no decoder_max_seq_length", str(refusal.exception))

    def test_without_one_it_runs_the_128_steps_of_the_bakeoff(self):
        _, metadata = self.run_with()
        self.assertEqual((metadata["decoder_max_seq_length"], metadata["decoder_max_seq_length_source"]), (128, "VietOCR default"))
        self.assertIsNone(metadata["project_config"])
        _, metadata = self.run_with("--decoder-max-seq-length", "160")
        self.assertEqual((metadata["decoder_max_seq_length"], metadata["decoder_max_seq_length_source"]), (160, "command line"))


if __name__ == "__main__":
    unittest.main()

"""The gates before a full run (batch probe, resume equivalence) and the rule that selects the final model."""

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

import _paths  # noqa: F401
import build_vietocr_config as builder
import check_resume_equivalence as gate
import dataset_common as dataset
import probe_cuda_batch as probe
import select_model
import train_vietocr as training
from dataset_common import BAKEOFF_REGRESSION, BLIND_TEST, REAL_VAL, SYNTHETIC_VAL

HAS_TORCH = importlib.util.find_spec("torch") is not None
NEEDS_TORCH = "needs PyTorch: run this file with .venv-vietocr/bin/python"


class BatchProbe(unittest.TestCase):
    def test_candidates_go_from_the_largest_batch_down_and_keep_the_effective_batch(self):
        self.assertEqual(probe.CANDIDATES, ((16, 1), (8, 2), (4, 4)))
        self.assertTrue(all(batch * accumulation == builder.EFFECTIVE_BATCH_SIZE == 16 for batch, accumulation in probe.CANDIDATES))

    def test_the_widest_experiment_is_the_one_probed(self):
        args, _ = probe.parse_args([])
        self.assertEqual(args.config, builder.config_path("exp_b_width1024"))
        self.assertEqual(probe.WIDEST_EXPERIMENT, max(builder.EXPERIMENTS, key=builder.EXPERIMENTS.get))

    def test_each_attempt_is_a_probe_run_of_the_training_script(self):
        command = probe.probe_command(Path("b.yml"), 8, 2, ["--device", "cuda:0"])
        self.assertEqual(command[0], sys.executable)
        self.assertEqual(command[1:], [str(dataset.DATASET_DIR / "train_vietocr.py"), "--config", "b.yml", "--probe-memory",
                                       "--batch-size", "8", "--accumulation-steps", "2", "--device", "cuda:0"])  # fmt: skip
        self.assertEqual(probe.OUT_OF_MEMORY_STATUS, training.OUT_OF_MEMORY_STATUS)

    def attempt(self, batch: int, accumulation: int, out_of_memory: bool, finite: bool = True) -> dict:
        return {"physical_batch_size": batch, "accumulation_steps": accumulation, "effective_batch_size": 16,
                "out_of_memory": out_of_memory, "loss_finite": finite and not out_of_memory}  # fmt: skip

    def test_the_first_attempt_that_fits_is_chosen(self):
        self.assertEqual(probe.choose([self.attempt(16, 1, False)])["physical_batch_size"], 16)
        chosen = probe.choose([self.attempt(16, 1, True), self.attempt(8, 2, False)])
        self.assertEqual((chosen["physical_batch_size"], chosen["accumulation_steps"]), (8, 2))
        self.assertEqual(probe.flags(chosen), "--batch-size 8 --accumulation-steps 2")
        self.assertIsNone(probe.choose([self.attempt(16, 1, True), self.attempt(8, 2, True), self.attempt(4, 4, True)]))

    def test_an_attempt_whose_loss_was_not_finite_does_not_count(self):
        self.assertIsNone(probe.choose([self.attempt(16, 1, False, finite=False)]))


class ResumeGateCommands(unittest.TestCase):
    def test_three_processes_one_uninterrupted_one_stopped_one_resumed(self):
        first, second, third = gate.commands(Path("a.yml"), 40, ["--batch-size", "8", "--accumulation-steps", "2"])
        for command in (first, second, third):
            self.assertEqual(command[:5], [sys.executable, str(dataset.DATASET_DIR / "train_vietocr.py"), "--config", "a.yml", "--smoke"])
            self.assertIn("--batch-size", command)  # the settings of the real run are passed on
        self.assertEqual(first[-5:], ["--run-name", "resume_gate_continuous", "--steps", "40", "--overwrite"])
        self.assertEqual(second[-5:], ["--run-name", "resume_gate_resumed", "--steps", "20", "--overwrite"])
        self.assertEqual(third[-5:], ["--run-name", "resume_gate_resumed", "--steps", "40", "--resume"])
        self.assertEqual(gate.STEPS, 40)

    def test_an_odd_number_of_steps_is_refused(self):
        with self.assertRaises(SystemExit):
            gate.main(["--config", str(builder.config_path("exp_a_width512")), "--steps", "41"])

    def test_the_gate_keeps_no_checkpoint_unless_asked(self):
        source = (dataset.DATASET_DIR / "check_resume_equivalence.py").read_text(encoding="utf-8")
        self.assertIn('for file in (directory / name).glob("*.pth"):', source)
        self.assertIn("if not args.keep_files:", source)


@unittest.skipUnless(HAS_TORCH, NEEDS_TORCH)
class ResumeGateComparison(unittest.TestCase):
    def state(self, steps: int = 40, shift: float = 0.0, loss_shift: float = 0.0, lr: float = 4.9e-06) -> dict:
        import torch

        generator = torch.Generator().manual_seed(3)
        weights = {"cnn.weight": torch.rand(4, 3, generator=generator) + shift, "cnn.bn.running_mean": torch.zeros(4),
                   "cnn.bn.num_batches_tracked": torch.tensor(0)}  # fmt: skip
        return {
            "step": steps,
            "model": weights,
            "optimizer": {"state": {0: {"step": torch.tensor(float(steps)), "exp_avg": torch.rand(4, 3, generator=generator) + shift}},
                          "param_groups": [{"lr": lr, "betas": (0.9, 0.98), "eps": 1e-09, "weight_decay": 0.01}]},
            "scheduler": {"last_epoch": steps, "_last_lr": [lr], "total_steps": 4670},
            "torch_rng": torch.arange(8),
            "cuda_rng": [torch.arange(8)],
            "record": {"step_losses": [1.0 + 0.01 * i + (loss_shift if i >= 20 else 0.0) for i in range(steps)]},
        }  # fmt: skip

    def test_identical_states_pass(self):
        verdict = gate.compare(self.state(), self.state(), 40)
        self.assertEqual((verdict["result"], verdict["identical"]), ("PASS", True))
        self.assertEqual(set(verdict["parts"]), {"model_state_dict", "optimizer_state", "scheduler_state", "learning_rate", "optimizer_steps",
                                                 "losses_of_steps_21_to_40", "losses_of_all_steps", "random_state", "cuda_random_states"})  # fmt: skip
        self.assertTrue(all(part["identical"] and part["largest_absolute_difference"] == 0.0 for part in verdict["parts"].values()))

    def test_cuda_rng_state_difference_is_reported(self):
        first, second = self.state(), self.state()
        second["cuda_rng"][0][0] += 1
        verdict = gate.compare(first, second, 40)
        self.assertEqual(verdict["result"], "FAIL")
        self.assertFalse(verdict["parts"]["cuda_random_states"]["identical"])
    def test_a_difference_fails_and_its_size_is_reported(self):
        verdict = gate.compare(self.state(), self.state(shift=1e-5), 40)
        self.assertEqual(verdict["result"], "FAIL")
        self.assertFalse(verdict["parts"]["model_state_dict"]["identical"])
        self.assertAlmostEqual(verdict["parts"]["model_state_dict"]["largest_absolute_difference"], 1e-5, delta=2e-6)
        self.assertAlmostEqual(verdict["parts"]["optimizer_state"]["largest_absolute_difference"], 1e-5, delta=2e-6)
        self.assertTrue(verdict["parts"]["scheduler_state"]["identical"])

    def test_losses_after_the_resume_are_compared_step_by_step(self):
        verdict = gate.compare(self.state(), self.state(loss_shift=0.25), 40)
        self.assertEqual(verdict["result"], "FAIL")
        self.assertAlmostEqual(verdict["parts"]["losses_of_steps_21_to_40"]["largest_absolute_difference"], 0.25)
        self.assertTrue(verdict["parts"]["model_state_dict"]["identical"])

    def test_another_learning_rate_or_step_count_fails(self):
        self.assertFalse(gate.compare(self.state(), self.state(lr=5e-06), 40)["parts"]["learning_rate"]["identical"])
        short = gate.compare(self.state(), self.state(steps=39), 40)
        self.assertEqual((short["result"], short["both_runs_reached_the_last_step"]), ("FAIL", False))

    def test_a_tolerance_is_accepted_only_when_stated(self):
        close = self.state(shift=1e-7)
        self.assertEqual(gate.compare(self.state(), close, 40)["result"], "FAIL")
        accepted = gate.compare(self.state(), close, 40, tolerance=1e-6)
        self.assertEqual((accepted["result"], accepted["identical"], accepted["tolerance"]), ("PASS", False, 1e-6))
        self.assertEqual(gate.compare(self.state(), self.state(shift=1e-3), 40, tolerance=1e-6)["result"], "FAIL")

    def test_values_that_cannot_be_compared_count_as_different(self):
        import torch

        self.assertEqual(gate.largest_difference(torch.zeros(3), torch.zeros(4)), float("inf"))
        self.assertEqual(gate.largest_difference({"a": 1}, {"b": 1}), float("inf"))
        self.assertEqual(gate.largest_difference([1, 2], [1, 2, 3]), float("inf"))
        self.assertEqual(gate.largest_difference(True, False), float("inf"))
        self.assertEqual(gate.largest_difference((0.9, 0.98), (0.9, 0.98)), 0.0)


class ModelSelection(unittest.TestCase):
    def evaluation(self, real: tuple, regression: tuple, synthetic: tuple = (0.03, 0.08, 0.6), blind: dict | None = None) -> dict:
        def result(values: tuple) -> dict:
            return {"lines": 100, "scored_lines": 100, "cer_nfc": values[0], "wer_nfc": values[1], "exact_line_nfc": values[2],
                    "decoder_limit_hits": 0, "runtime_seconds": 10.0}  # fmt: skip

        results = {REAL_VAL: result(real), SYNTHETIC_VAL: result(synthetic), BAKEOFF_REGRESSION: result(regression)}
        results[BLIND_TEST] = blind or {"lines": 100, "status": "LOCKED", "predictions_not_scored": 0}
        return {"label": "x", "results": results}

    BASELINE = ((0.0448, 0.1064, 0.56), (0.0451, 0.0883, 0.57))

    def test_the_lowest_real_validation_cer_is_selected(self):
        decision = select_model.choose({"a": self.evaluation((0.030, 0.09, 0.6), (0.040, 0.08, 0.6)),
                                        "b": self.evaluation((0.025, 0.12, 0.5), (0.044, 0.09, 0.6))}, self.evaluation(*self.BASELINE))  # fmt: skip
        self.assertEqual((decision["selected"], decision["ranking"]), ("b", ["b", "a"]))
        self.assertFalse(decision["blind_test_used"])
        self.assertIn("lowest real_val CER", decision["reason"])

    def test_a_tie_on_cer_is_broken_by_wer(self):
        decision = select_model.choose({"a": self.evaluation((0.030, 0.09, 0.9), (0.04, 0.08, 0.6)),
                                        "b": self.evaluation((0.030, 0.08, 0.1), (0.04, 0.08, 0.6))}, self.evaluation(*self.BASELINE))  # fmt: skip
        self.assertEqual(decision["selected"], "b")  # exact-line accuracy plays no part

    def test_synthetic_validation_decides_nothing(self):
        decision = select_model.choose({"a": self.evaluation((0.030, 0.09, 0.6), (0.04, 0.08, 0.6), synthetic=(0.50, 0.9, 0.0)),
                                        "b": self.evaluation((0.031, 0.09, 0.6), (0.04, 0.08, 0.6), synthetic=(0.00, 0.0, 1.0))},
                                       self.evaluation(*self.BASELINE))  # fmt: skip
        self.assertEqual(decision["selected"], "a")

    def test_no_candidate_is_selected_unless_it_beats_the_pretrained_model(self):
        decision = select_model.choose({"a": self.evaluation((0.050, 0.11, 0.5), (0.04, 0.08, 0.6)),
                                        "b": self.evaluation((0.300, 0.40, 0.3), (0.30, 0.39, 0.2))}, self.evaluation(*self.BASELINE))  # fmt: skip
        self.assertIsNone(decision["selected"])
        self.assertIn("no candidate reads real_val better", decision["reason"])
        self.assertEqual(decision["ranking"], ["a", "b"])

    def test_a_worse_regression_score_is_flagged_for_review_not_hidden(self):
        decision = select_model.choose({"a": self.evaluation((0.030, 0.09, 0.6), (0.060, 0.10, 0.5))}, self.evaluation(*self.BASELINE))
        entry = decision["candidates"]["a"]
        self.assertEqual((decision["selected"], entry["regression_sanity"]), ("a", "REVIEW"))
        self.assertAlmostEqual(entry["regression_cer_change"], 0.060 - 0.0451)
        self.assertIn("regression sanity: REVIEW", decision["reason"])
        better = select_model.choose({"a": self.evaluation((0.030, 0.09, 0.6), (0.0451, 0.10, 0.5))}, self.evaluation(*self.BASELINE))
        self.assertEqual(better["candidates"]["a"]["regression_sanity"], "PASS")

    def write(self, directory: Path, **evaluations: dict) -> None:
        for label, evaluation in evaluations.items():
            (directory / f"{label}.json").write_text(json.dumps(evaluation), encoding="utf-8")

    def run_selection(self, root: Path, *labels: str):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            status = select_model.main(["--evaluations-dir", str(root / "manifests" / "evaluations"), "--root", str(root),
                                        "--candidates", *labels, "--baseline", "base"])  # fmt: skip
        return status, output.getvalue()

    def test_the_command_writes_the_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evaluations = root / "manifests" / "evaluations"
            evaluations.mkdir(parents=True)
            self.write(evaluations, base=self.evaluation(*self.BASELINE), a=self.evaluation((0.030, 0.09, 0.6), (0.04, 0.08, 0.6)),
                       b=self.evaluation((0.028, 0.10, 0.6), (0.05, 0.09, 0.5)))  # fmt: skip
            status, output = self.run_selection(root, "a", "b")
            self.assertEqual(status, 0)
            self.assertIn("SELECTED: b", output)
            self.assertIn("blind test: not used, still locked", output)
            decision = json.loads((evaluations / "phase4_selection.json").read_text(encoding="utf-8"))
            self.assertEqual((decision["selected"], decision["candidates"]["b"]["regression_sanity"]), ("b", "REVIEW"))
            self.assertNotIn(BLIND_TEST, json.dumps(decision["candidates"]))

    def test_it_refuses_evaluations_that_hold_blind_scores(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evaluations = root / "manifests" / "evaluations"
            evaluations.mkdir(parents=True)
            scored = self.evaluation((0.03, 0.09, 0.6), (0.04, 0.08, 0.6), blind={"lines": 100, "cer_nfc": 0.02, "wer_nfc": 0.05})
            self.write(evaluations, base=self.evaluation(*self.BASELINE), a=scored)
            with self.assertRaises(SystemExit) as refusal:
                self.run_selection(root, "a")
            self.assertIn("scores of the blind test", str(refusal.exception))
            self.assertFalse((evaluations / "phase4_selection.json").exists())

    def test_it_refuses_to_select_after_the_blind_test_was_unlocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evaluations = root / "manifests" / "evaluations"
            evaluations.mkdir(parents=True)
            self.write(evaluations, base=self.evaluation(*self.BASELINE), a=self.evaluation((0.03, 0.09, 0.6), (0.04, 0.08, 0.6)))
            (root / "manifests" / "blind_test_unlocks.jsonl").write_text(json.dumps({"label": "a", "reason": "r", "by": "x"}) + "\n", encoding="utf-8")
            with self.assertRaises(SystemExit) as refusal:
                self.run_selection(root, "a")
            self.assertIn("blind test has been unlocked", str(refusal.exception))

    def test_the_defaults_are_the_two_experiments_against_the_pretrained_model_at_512(self):
        self.assertEqual(select_model.CANDIDATES, ("phase4_exp_a_width512", "phase4_exp_b_width1024"))
        self.assertEqual(select_model.BASELINE, "phase4_pretrained_w512")
        baseline = json.loads((dataset.MANIFESTS_DIR / "evaluations" / "phase4_pretrained_w512.json").read_text(encoding="utf-8"))
        self.assertEqual(baseline["results"][BLIND_TEST]["status"], "LOCKED")
        self.assertAlmostEqual(baseline["results"][REAL_VAL]["cer_nfc"], 0.044828, places=6)


if __name__ == "__main__":
    unittest.main()

"""Guardrails for the frozen VietOCR B ONNX exporter and non-blind parity gate.

Runs without ONNX Runtime or the model checkpoint, so these safety checks can
be used before the GPU machine's export dependencies are installed.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import _paths  # noqa: F401  (adds dataset scripts and benchmark helpers to sys.path)
import check_vietocr_onnx_parity as parity
import export_vietocr_onnx as exporter


class FrozenExport(unittest.TestCase):
    def test_checkpoint_fingerprint_is_frozen(self):
        self.assertEqual(
            exporter.CHECKPOINT_SHA256,
            "a2f9d737edca1b2d5d45231b34601a0eb573aafd0fde3202cf6d20601de3edb3",
        )
        self.assertEqual(exporter.SELECTED, "phase4_exp_b_width1024")

    def test_nonblind_split_contract(self):
        self.assertEqual(parity.EXPECTED_SPLITS, {
            "real_val": 100, "synthetic_val": 552, "bakeoff_regression": 100
        })
        self.assertNotIn("blind_test", parity.EXPECTED_SPLITS)

    def test_nonblind_manifest_accepts_exact_split_counts(self):
        rows = [
            {"id": f"{split}_{i}", "split": split}
            for split, count in parity.EXPECTED_SPLITS.items()
            for i in range(count)
        ]
        parity.validate_manifest(rows)
        with self.assertRaises(SystemExit):
            parity.validate_manifest([*rows, {"id": "blind_0", "split": "blind_test"}])
        with self.assertRaises(SystemExit):
            parity.validate_manifest([*rows[:-1], rows[0]])

    def test_missing_or_wrong_reference_metadata_fails_closed(self):
        rows = [
            {"id": f"{split}_{i}", "split": split}
            for split, count in parity.EXPECTED_SPLITS.items()
            for i in range(count)
        ]
        with tempfile.TemporaryDirectory() as directory:
            predictions = Path(directory) / "predictions.jsonl"
            with predictions.open("w", encoding="utf-8") as stream:
                for row in rows:
                    stream.write(json.dumps({"id": row["id"], "prediction": "abc"}) + "\n")
            with self.assertRaises(SystemExit):
                parity.verify_reference(rows, predictions)
            predictions.with_suffix(".meta.json").write_text(
                json.dumps({
                    "weights_sha256": "not-the-frozen-checkpoint",
                    "image_max_width": 1024,
                    "decoder_max_seq_length": 128,
                }), encoding="utf-8"
            )
            with self.assertRaises(SystemExit):
                parity.verify_reference(rows, predictions)
            predictions.with_suffix(".meta.json").write_text(
                json.dumps({
                    "weights_sha256": exporter.CHECKPOINT_SHA256,
                    "image_max_width": 1024,
                    "decoder_max_seq_length": 128,
                }), encoding="utf-8"
            )
            expected = parity.verify_reference(rows, predictions)
            self.assertEqual(len(expected), 752)


if __name__ == "__main__":
    unittest.main()

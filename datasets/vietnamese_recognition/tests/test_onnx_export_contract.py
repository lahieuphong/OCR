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


class DynamicAttentionContract(unittest.TestCase):
    def test_attention_matches_pytorch_for_variable_lengths(self):
        import torch
        from torch import nn
        from onnx_attention import DynamicSequenceAttention

        torch.manual_seed(37)
        original = nn.MultiheadAttention(64, 8, dropout=0.1, batch_first=False).eval()
        rewritten = DynamicSequenceAttention(original).eval()
        with torch.inference_mode():
            for query_length, memory_length in ((1, 32), (8, 8), (16, 40), (32, 16)):
                query = torch.randn(query_length, 1, 64)
                key = torch.randn(memory_length, 1, 64)
                value = torch.randn(memory_length, 1, 64)
                mask = torch.zeros(query_length, memory_length)
                if query_length == memory_length:
                    mask = nn.Transformer.generate_square_subsequent_mask(query_length)
                expected, _ = original(
                    query, key, value, attn_mask=mask, need_weights=False
                )
                actual, _ = rewritten(
                    query, key, value, attn_mask=mask, need_weights=False
                )
                self.assertTrue(
                    torch.allclose(expected, actual, atol=1e-5, rtol=1e-5),
                    f"lengths {(query_length, memory_length)} differ: "
                    f"{(expected - actual).abs().max().item()}",
                )

    def test_transformer_replacement_does_not_touch_original(self):
        import copy
        import torch
        from torch import nn
        from onnx_attention import DynamicSequenceAttention, replace_attention_for_export

        original = nn.Transformer(
            d_model=32, nhead=4, num_encoder_layers=2,
            num_decoder_layers=2, dim_feedforward=64, dropout=0.0,
        ).eval()
        rewritten = copy.deepcopy(original)
        self.assertEqual(replace_attention_for_export(rewritten), 6)
        self.assertEqual(sum(isinstance(m, nn.MultiheadAttention) for m in original.modules()), 6)
        self.assertEqual(sum(isinstance(m, nn.MultiheadAttention) for m in rewritten.modules()), 0)
        self.assertEqual(sum(isinstance(m, DynamicSequenceAttention) for m in rewritten.modules()), 6)
        with torch.inference_mode():
            src = torch.randn(24, 1, 32)
            tgt = torch.randn(10, 1, 32)
            tgt_mask = nn.Transformer.generate_square_subsequent_mask(10)
            expected = original(src, tgt, tgt_mask=tgt_mask)
            actual = rewritten(src, tgt, tgt_mask=tgt_mask)
        self.assertTrue(torch.allclose(expected, actual, atol=1e-4, rtol=1e-4))


class FrozenExport(unittest.TestCase):
    def test_checkpoint_fingerprint_is_frozen(self):
        self.assertEqual(
            exporter.CHECKPOINT_SHA256,
            "a2f9d737edca1b2d5d45231b34601a0eb573aafd0fde3202cf6d20601de3edb3",
        )
        self.assertEqual(exporter.SELECTED, "phase4_exp_b_width1024")

    def test_positive_cnn_axes_preserve_pinned_sequence_layout(self):
        import torch

        # Pinned VietOCR Vgg.forward uses negative axis indices. ONNX
        # requires an explicit non-negative permutation.
        for height, width in ((1, 10), (2, 25), (1, 64)):
            features = torch.arange(2 * 256 * height * width, dtype=torch.float32).reshape(
                2, 256, height, width
            )
            pinned = features.transpose(-1, -2).flatten(2).permute(-1, 0, 1)
            onnx_safe = features.transpose(2, 3).flatten(2).permute(2, 0, 1)
            self.assertTrue(torch.equal(pinned, onnx_safe))
            self.assertEqual(onnx_safe.shape, (height * width, 2, 256))

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

#!/usr/bin/env python3
r"""Export the FROZEN VietOCR B width-1024 recognizer as encoder/decoder-step ONNX graphs.

This is *not* a production deployment command. Run parity verification before
integrating the artifacts into any OCR pipeline.

Windows CMD:
    .venv-vietocr\Scripts\python.exe datasets\vietnamese_recognition\export_vietocr_onnx.py

Requires packages: onnx, onnxruntime (for independent graph shape validation).
Uses the pinned VietOCR implementation from third_party/vietocr and never
changes the model checkpoint, training set, or blind-test results.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml

import dataset_common as dataset

# Official checkpoint from the one-time selected-model evaluation.
SELECTED = "phase4_exp_b_width1024"
CHECKPOINT_SHA256 = "a2f9d737edca1b2d5d45231b34601a0eb573aafd0fde3202cf6d20601de3edb3"
CONFIG = dataset.REPO_ROOT / "configs/vietnamese/vietocr/exp_b_width1024.yml"
WEIGHTS = dataset.REPO_ROOT / "models/vietocr/finetuned/exp_b_width1024/weights.pth"
OUTPUT = dataset.REPO_ROOT / "models/vietocr/onnx/exp_b_width1024"
OPSET = 17


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def preflight(config_path: Path, weights_path: Path) -> dict:
    selection_file = dataset.DATASET_DIR / "manifests/evaluations/phase4_selection.json"
    if not selection_file.is_file():
        raise SystemExit(f"STOP: selected-model report missing: {selection_file}")
    selection = json.loads(selection_file.read_text(encoding="utf-8"))
    if selection.get("selected") != SELECTED:
        raise SystemExit("STOP: selection is not frozen VietOCR B width1024")
    digest = sha256(weights_path)
    if digest != CHECKPOINT_SHA256:
        raise SystemExit(f"STOP: checkpoint SHA-256 differs: {digest}")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if (config["dataset"]["image_max_width"] != 1024
            or config["experiment"]["name"] != "exp_b_width1024"
            or config["decoder_max_seq_length"] != 128):
        raise SystemExit("STOP: B config differs from frozen width/decoder settings")
    if config["predictor"]["beamsearch"]:
        raise SystemExit("STOP: only the evaluated greedy decoder can be exported")
    return config


def build_export_models(config_path: Path, weights_path: Path):
    # Import after pinned checkout path has been established.
    import copy
    import run_vietocr
    import torch
    from torch import nn
    from onnx_attention import replace_attention_for_export

    run_vietocr.check_pinned_checkout()
    sys.dont_write_bytecode = True
    if str(run_vietocr.VIETOCR_DIR) not in sys.path:
        sys.path.insert(0, str(run_vietocr.VIETOCR_DIR))
    from vietocr.tool.translate import build_model
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["device"] = "cpu"
    config["cnn"]["pretrained"] = False
    model, vocab = build_model(config)
    model.load_state_dict(torch.load(weights_path, map_location="cpu", weights_only=True))
    model.eval()

    # Keep an untouched pinned reference for numeric checks. The ONNX-only
    # copy uses explicit attention matmul/softmax, avoiding sequence-length
    # constants in legacy MultiheadAttention tracing.
    export_model = copy.deepcopy(model)
    replaced = replace_attention_for_export(export_model)
    if replaced != 18:
        raise SystemExit(f"STOP: expected 18 transformer attention modules; got {replaced}")
    export_model.eval()

    class Encoder(nn.Module):
        def __init__(self, recognizer):
            super().__init__()
            self.cnn = recognizer.cnn
            self.transformer = recognizer.transformer

        def forward(self, image):
            # The pinned Vgg.forward ends with:
            #   conv.transpose(-1, -2).flatten(2).permute(-1, 0, 1)
            # PyTorch accepts a negative permutation index, but ONNX
            # Transpose.perm ONLY accepts indices in [0, rank).
            # Re-express the SAME operations with positive axis indices.
            # Do not patch or change the pinned VietOCR submodule.
            vgg = self.cnn.model
            conv = vgg.features(image)
            conv = vgg.dropout(conv)
            conv = vgg.last_conv_1x1(conv)
            sequence = conv.transpose(2, 3).flatten(2).permute(2, 0, 1)
            return self.transformer.forward_encoder(sequence)

    class DecoderStep(nn.Module):
        def __init__(self, recognizer):
            super().__init__()
            self.transformer = recognizer.transformer

        def forward(self, tokens, memory):
            logits, _ = self.transformer.forward_decoder(tokens, memory)
            return logits[:, -1, :]

    return model, vocab, Encoder(export_model).eval(), DecoderStep(export_model).eval()


def export(config_path: Path, weights_path: Path, output_dir: Path, overwrite: bool) -> dict:
    import onnx
    import onnxruntime as ort
    import torch

    config = preflight(config_path, weights_path)
    encoder_path = output_dir / "encoder.onnx"
    decoder_path = output_dir / "decoder_step.onnx"
    metadata_path = output_dir / "metadata.json"
    if not overwrite and any(path.exists() for path in (encoder_path, decoder_path, metadata_path)):
        raise SystemExit(f"STOP: output already exists in {output_dir}; do not overwrite without --overwrite")
    output_dir.mkdir(parents=True, exist_ok=True)
    model, vocab, encoder, decoder = build_export_models(config_path, weights_path)
    # Avoid PyTorch's optimized MHA inference fastpath (fused ATen ops may
    # not have equivalent standard ONNX operators in the legacy exporter).
    torch.backends.mha.set_fastpath_enabled(False)
    image = torch.zeros((1, 3, 32, 320), dtype=torch.float32)
    tokens = torch.tensor([[vocab.go], [vocab.c2i.get("a", 4)]], dtype=torch.long)

    # Guardrail: the ONNX-friendly layout must remain bit-for-bit equivalent
    # to the pinned PyTorch encoder; test several *non-zero* inputs/widths
    # before any export. No blind-test images are involved.
    with torch.inference_mode():
        for width in (160, 320, 640, 1024):
            probe = torch.linspace(0.0, 1.0, steps=3 * 32 * width).reshape(1, 3, 32, width)
            pinned = model.transformer.forward_encoder(model.cnn(probe))
            rewritten = encoder(probe)
            if not torch.allclose(pinned, rewritten, atol=1e-4, rtol=1e-4):
                delta = (pinned - rewritten).abs().max().item()
                raise SystemExit(f"STOP: attention rewrite differs numerically from pinned encoder at width {width}: {delta}")
            # Check the entire decoder as well: self-attention with a causal
            # mask and cross-attention on the variable-width encoder memory.
            for prefix_length in (1, 2, 16):
                prefix = torch.ones((prefix_length, 1), dtype=torch.long)
                reference_logits, _ = model.transformer.forward_decoder(prefix, pinned)
                export_logits = decoder(prefix, rewritten)
                reference_last = reference_logits[:, -1, :]
                if not torch.allclose(reference_last, export_logits, atol=5e-4, rtol=1e-4):
                    delta = (reference_last - export_logits).abs().max().item()
                    raise SystemExit(
                        f"STOP: attention rewrite differs from pinned decoder at width {width}, "
                        f"prefix {prefix_length}: {delta}"
                    )

    # The encoder must support image widths beyond the tracing example;
    # the decoder must support varying source widths and target prefix lengths.
    # The model is fixed to batch 1; do not advertise dynamic batch.
    with torch.inference_mode():
        memory = encoder(image)
        torch.onnx.export(
            encoder, (image,), str(encoder_path),
            input_names=["image"], output_names=["memory"],
            dynamic_axes={"image": {3: "image_width"}, "memory": {0: "source_length"}},
            opset_version=OPSET, do_constant_folding=True, dynamo=False,
        )
        torch.onnx.export(
            decoder, (tokens, memory), str(decoder_path),
            input_names=["tokens", "memory"], output_names=["logits"],
            dynamic_axes={"tokens": {0: "target_length"}, "memory": {0: "source_length"}},
            opset_version=OPSET, do_constant_folding=True, dynamo=False,
        )

    for path in (encoder_path, decoder_path):
        onnx.checker.check_model(str(path))
    # Fail early if graphs cannot be loaded or are accidentally fixed at the
    # tracing dimensions. Full character-by-character parity is a separate gate.
    providers = ["CPUExecutionProvider"]
    enc_session = ort.InferenceSession(str(encoder_path), providers=providers)
    dec_session = ort.InferenceSession(str(decoder_path), providers=providers)
    for width in (160, 320, 640, 1024):
        with torch.inference_mode():
            sample = torch.zeros((1, 3, 32, width), dtype=torch.float32)
            expected = encoder(sample).numpy()
        observed = enc_session.run(["memory"], {"image": sample.numpy()})[0]
        if observed.shape != expected.shape:
            raise SystemExit(f"STOP: encoder dynamic width {width}: {observed.shape} != {expected.shape}")
        for prefix_length in (1, 2, 16):
            seq = torch.ones((prefix_length, 1), dtype=torch.long)
            logits = dec_session.run(
                ["logits"], {"tokens": seq.numpy(), "memory": observed}
            )[0]
            if logits.shape != (1, len(vocab)):
                raise SystemExit(
                    f"STOP: decoder dynamic prefix {prefix_length}, width {width}: got {logits.shape}"
                )
    info = {
        "status": "EXPORTED_NOT_YET_PARITY_VERIFIED",
        "selected": SELECTED,
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "config_sha256": sha256(config_path),
        "config_path": config_path.relative_to(dataset.REPO_ROOT).as_posix(),
        "checkpoint_path": weights_path.relative_to(dataset.REPO_ROOT).as_posix(),
        "opset": OPSET,
        "exporter": "torch.onnx.export(dynamo=False), encoder/decoder-step with export-only dynamic MHA",
        "torch_version": torch.__version__,
        "onnx_version": onnx.__version__,
        "onnxruntime_version": ort.__version__,
        "image_height": 32,
        "image_min_width": int(config["dataset"]["image_min_width"]),
        "image_max_width": 1024,
        "decoder_max_seq_length": 128,
        "batch_size": 1,
        "preprocessing": "VietOCR process_input: PIL RGB/LANCZOS, width round up to 10, clamp, RGB float32/255, CHW",
        "decoding": "VietOCR greedy argmax with SOS=1, EOS=2; max_seq_length+1 steps (pinned implementation)",
        "vocab": vocab.chars,
        "vocab_size": len(vocab),
        "tokens": {"pad": vocab.pad, "sos": vocab.go, "eos": vocab.eos, "mask": vocab.mask_token},
        "encoder_sha256": sha256(encoder_path),
        "decoder_sha256": sha256(decoder_path),
        "required_next_gate": "check_vietocr_onnx_parity.py on all 752 non-blind evaluation crops",
    }
    metadata_path.write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return info


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--weights", type=Path, default=WEIGHTS)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    result = export(args.config.resolve(), args.weights.resolve(), args.output_dir.resolve(), args.overwrite)
    print("ONNX GRAPHS EXPORTED; NOT YET APPROVED FOR DEPLOYMENT")
    print(f"encoder_sha256: {result['encoder_sha256']}")
    print(f"decoder_sha256: {result['decoder_sha256']}")
    print(f"metadata: {args.output_dir / 'metadata.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

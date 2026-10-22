"""Fail-closed local demo model contract. No model downloads, training, or blind tests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = REPO_ROOT / "models/vietocr/onnx/exp_b_width1024"
WEIGHTS = REPO_ROOT / "models/vietocr/finetuned/exp_b_width1024/weights.pth"
CHECKPOINT_SHA256 = "a2f9d737edca1b2d5d45231b34601a0eb573aafd0fde3202cf6d20601de3edb3"
EXPECTED_ENCODER_SHA256 = "f20d629ad81171267b517794d9f23cbf48bd74d3b45c9747aa5a0930433c40f1"
EXPECTED_DECODER_SHA256 = "67029da541d1904ab04d6de3aec0b0cbe9ab3d2efca15108f155b4c5e4abeb51"
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_PDF_PAGES = 6
MAX_IMAGE_PIXELS = 12_000_000
ACCEPTED_EXTENSIONS = frozenset({".pdf", ".png", ".jpg", ".jpeg"})


class DemoConfigurationError(RuntimeError):
    """Local model artifacts are missing or differ from frozen experiments."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as reader:
        for data in iter(lambda: reader.read(1 << 20), b""):
            digest.update(data)
    return digest.hexdigest()


def verify_frozen_onnx(model_dir: Path = MODEL_DIR, *, require_weights: bool = True) -> dict:
    """Confirm exact selected checkpoint and graph bits; never use unknown weights."""
    try:
        metadata = json.loads((model_dir / "metadata.json").read_text(encoding="utf-8"))
        cpu = json.loads((model_dir / "parity_full.json").read_text(encoding="utf-8"))
        digests = {
            "encoder_sha256": sha256_file(model_dir / "encoder.onnx"),
            "decoder_sha256": sha256_file(model_dir / "decoder_step.onnx"),
        }
    except (OSError, ValueError) as error:
        raise DemoConfigurationError(
            "Missing/invalid ONNX files. Export and finish full CPU parity first."
        ) from error

    expected = {
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "encoder_sha256": EXPECTED_ENCODER_SHA256,
        "decoder_sha256": EXPECTED_DECODER_SHA256,
        "image_height": 32,
        "image_min_width": 32,
        "image_max_width": 1024,
        "decoder_max_seq_length": 128,
        "batch_size": 1,
        "status": "EXPORTED_NOT_YET_PARITY_VERIFIED",
    }
    for field, value in expected.items():
        if metadata.get(field) != value:
            raise DemoConfigurationError(f"STOP: frozen metadata {field} differs.")
    for field, value in digests.items():
        if metadata.get(field) != value or expected[field] != value:
            raise DemoConfigurationError(f"STOP: ONNX {field} SHA256 mismatch.")

    if not isinstance(metadata.get("vocab"), str) or len(metadata["vocab"]) + 4 != metadata.get("vocab_size"):
        raise DemoConfigurationError("STOP: frozen vocabulary metadata mismatch.")
    if (cpu.get("result") != "PASS"
            or cpu.get("checkpoint_sha256") != CHECKPOINT_SHA256
            or cpu.get("onnx_encoder_sha256") != EXPECTED_ENCODER_SHA256
            or cpu.get("onnx_decoder_sha256") != EXPECTED_DECODER_SHA256
            or cpu.get("scored_non_blind_lines") != 752
            or cpu.get("text_mismatches") != 0
            or cpu.get("decoder_limit_hits") != 0
            or cpu.get("blind_test_used") is not False):
        raise DemoConfigurationError("STOP: independent 752-line ONNX CPU parity is not PASS.")
    if require_weights:
        try:
            digest = sha256_file(WEIGHTS)
        except OSError as error:
            raise DemoConfigurationError("Missing selected B checkpoint; training weights must remain frozen.") from error
        if digest != CHECKPOINT_SHA256:
            raise DemoConfigurationError("STOP: selected VietOCR B checkpoint differs.")
    return metadata


def validate_upload(filename: str, content: bytes) -> str:
    """Validate both extension and actual header, without trusting the browser MIME."""
    ext = Path(filename or "").suffix.lower()
    if ext not in ACCEPTED_EXTENSIONS:
        raise ValueError("Chỉ hỗ trợ PDF, PNG, JPG/JPEG.")
    if not content:
        raise ValueError("Tài liệu rỗng.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("Tài liệu vượt quá giới hạn 15 MB.")
    if ext == ".pdf" and not content.startswith(b"%PDF-"):
        raise ValueError("Nội dung tệp không phải PDF hợp lệ.")
    if ext == ".png" and not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Nội dung tệp không phải PNG hợp lệ.")
    if ext in {".jpg", ".jpeg"} and not content.startswith(b"\xff\xd8\xff"):
        raise ValueError("Nội dung tệp không phải JPEG hợp lệ.")
    return ext


def decode_ids(ids: list[int], vocab: str) -> str:
    alphabet = {i + 4: char for i, char in enumerate(vocab)}
    alphabet.update({0: "<pad>", 1: "<sos>", 2: "<eos>", 3: "*"})
    start = 1 if 1 in ids else 0
    stop = ids.index(2) if 2 in ids else len(ids)
    try:
        return "".join(alphabet[id_] for id_ in ids[start:stop])
    except KeyError as error:
        raise RuntimeError(f"ONNX returned token outside vocab: {error}") from error

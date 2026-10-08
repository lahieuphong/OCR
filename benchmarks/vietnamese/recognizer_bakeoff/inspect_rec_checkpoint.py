#!/usr/bin/env python3
"""Which tensors of the PP-OCRv6_medium_rec training checkpoint depend on the dictionary.

Usage (PaddlePaddle environment, ``.venv``):
    python benchmarks/vietnamese/recognizer_bakeoff/inspect_rec_checkpoint.py

Feasibility study for extending the recognition head with the Vietnamese
letters the stock dictionary lacks. Every statement it prints is measured on
the vendored model code and the official *training* checkpoint:

    1. the checkpoint fits the architecture of the vendored training config;
    2. which tensors change shape when the model is built for the extended
       dictionary, found by building both models and comparing them;
    3. where each existing class lands in the extended class list;
    4. what the vendored loader does with the tensors that no longer fit;
    5. whether copying the old rows to their new positions preserves the
       pretrained behaviour, checked on the exported line crops;
    6. how the choice of initial values for the new rows changes the output
       of the model before any training.

Nothing is trained and no checkpoint is written: the extended model only ever
exists in memory. The findings are written up in ``PP_OCRV6_HEAD_ANALYSIS.md``.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import itertools
import logging
import sys
import unicodedata
import warnings
from pathlib import Path

import bakeoff_common as bakeoff
from audit_charset import PPOCRV6_DICT
from build_extended_dict import EXTENDED_DICT, VENDOR_DIR
from evaluate import write_csv

CONFIG = VENDOR_DIR / "configs" / "rec" / "PP-OCRv6" / "PP-OCRv6_medium_rec.yml"
CHECKPOINT = bakeoff.MODELS_DIR / "pretrained" / "PP-OCRv6_medium_rec_pretrained.pdparams"
CHECKPOINT_URL = (
    "https://paddle-model-ecology.bj.bcebos.com/paddlex/official_pretrained_model/"
    "PP-OCRv6_medium_rec_pretrained.pdparams"
)
CHECKPOINT_SHA256 = "c4a110423c23739f157ff870e27f41649d8c89e4c8df5230c2cd2e9fd90a7e92"
CTC_WEIGHT, CTC_BIAS = "head.ctc_head.fc.weight", "head.ctc_head.fc.bias"
# The NRTR decoder embeds and predicts one more index than the label encoder
# defines (`Transformer.__init__`: `self.out_channels = out_channels + 1`).
NRTR_UNUSED_ROW = "<unused trailing row>"
STATE_DICT_COLUMNS = ("name", "shape", "parameters", "vocabulary_dependent", "shape_with_extended_dict")


def load_rec_postprocess():
    """The vendored ``ppocr/postprocess/rec_postprocess.py`` as a module.

    Loaded by path: importing the ``ppocr.postprocess`` package pulls in every
    post-processor, and one of them needs scikit-image, which the baseline
    environment does not have.
    """
    path = VENDOR_DIR / "ppocr" / "postprocess" / "rec_postprocess.py"
    spec = importlib.util.spec_from_file_location("vendored_rec_postprocess", path)
    module = importlib.util.module_from_spec(spec)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)  # regex literals in that file
        spec.loader.exec_module(module)
    return module


def class_lists(codecs, dictionary: Path, use_space_char: bool) -> dict[str, list[str]]:
    """Class index -> character for both heads, as the vendored label codecs define it."""
    return {
        "ctc": list(codecs.CTCLabelDecode(str(dictionary), use_space_char).character),
        "nrtr": list(codecs.NRTRLabelDecode(str(dictionary), use_space_char).character)
        + [NRTR_UNUSED_ROW],
    }


def build(config: dict, ctc_classes: int):
    """The model ``tools/train.py`` builds when CTCLabelDecode has ``ctc_classes`` classes."""
    from ppocr.modeling.architectures import build_model

    if (
        config["PostProcess"]["name"] != "CTCLabelDecode"
        or "NRTRLoss" not in config["Loss"]["loss_config_list"][1]
    ):
        raise SystemExit("The config is not the CTC + NRTR MultiHead setup this script mirrors.")
    architecture = copy.deepcopy(config["Architecture"])
    # tools/train.py, MultiHead branch: one CTC output per class, three more for NRTR.
    architecture["Head"]["out_channels_list"] = {
        "CTCLabelDecode": ctc_classes,
        "NRTRLabelDecode": ctc_classes + 3,
    }
    model = build_model(architecture)
    model.eval()
    return model


def shapes(state: dict) -> dict[str, tuple[int, ...]]:
    return {name: tuple(value.shape) for name, value in state.items()}


def index_map(old: list[str], new: list[str]) -> list[int]:
    """New class index of every old class, matched by the character it stands for."""
    if len(set(old)) != len(old) or len(set(new)) != len(new):
        raise SystemExit("A class list holds the same character twice; cannot map by character.")
    position = {character: index for index, character in enumerate(new)}
    return [position[character] for character in old]


def migrate(old_tensor, fresh_tensor, mapping: list[int]):
    """``fresh_tensor`` with the old classes copied to their new positions."""
    import numpy as np

    axes = [axis for axis, size in enumerate(old_tensor.shape) if size != fresh_tensor.shape[axis]]
    if len(axes) != 1 or old_tensor.shape[axes[0]] != len(mapping):
        raise SystemExit(f"Cannot tell the class axis of a tensor of shape {old_tensor.shape}.")
    migrated = np.array(fresh_tensor, copy=True)
    selection = [slice(None)] * migrated.ndim
    selection[axes[0]] = mapping
    migrated[tuple(selection)] = old_tensor
    return migrated


def nearest_existing_letter(character: str, existing: set[str]) -> str | None:
    """The letter in ``existing`` with the same base and the fewest marks removed."""
    base, *marks = unicodedata.normalize("NFD", character)
    for kept in range(len(marks) - 1, -1, -1):
        for subset in itertools.combinations(marks, kept):
            candidate = unicodedata.normalize("NFC", base + "".join(subset))
            if len(candidate) == 1 and candidate in existing:
                return candidate
    return None


def new_row_strategies(weight, bias, old_classes: list[str], new_classes: list[str]) -> dict:
    """Ways to initialise the CTC rows of the added classes: name -> (weight, bias).

    ``weight`` and ``bias`` are the migrated tensors, whose new rows still hold
    the head's own random initialisation.
    """
    added = [index for index, character in enumerate(new_classes) if character not in set(old_classes)]
    old_index = {character: index for index, character in enumerate(new_classes)}
    quiet_bias = float(bias[[old_index[c] for c in old_classes]].min())

    silent_weight, silent_bias = weight.copy(), bias.copy()
    silent_weight[:, added] = 0.0
    silent_bias[added] = quiet_bias

    nearest_weight, nearest_bias = weight.copy(), bias.copy()
    for index in added:
        source = old_index[nearest_existing_letter(new_classes[index], set(old_classes))]
        nearest_weight[:, index] = weight[:, source]
        nearest_bias[index] = bias[source]

    return {
        "random (the head's own initialiser)": (weight, bias),
        f"silent (zero weight, bias {quiet_bias:.2f} = lowest old bias)": (silent_weight, silent_bias),
        "copy of the nearest existing letter": (nearest_weight, nearest_bias),
    }


def loader_report(model, checkpoint_path: Path, checkpoint: dict) -> tuple[list[str], list[str]]:
    """Run the vendored pretrained-weights loader; return its warnings and what it skipped."""
    import numpy as np
    from ppocr.utils.logging import get_logger
    from ppocr.utils.save_load import load_pretrained_params

    messages: list[str] = []

    class Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.levelno >= logging.WARNING:
                messages.append(record.getMessage())

    logger, handler = get_logger(), Collect()
    logger.addHandler(handler)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # Paddle repeats each skipped tensor
            load_pretrained_params(model, str(checkpoint_path))
    finally:
        logger.removeHandler(handler)
    state = {name: value.numpy() for name, value in model.state_dict().items()}
    not_loaded = [
        name
        for name, value in checkpoint.items()
        if state[name].shape != value.shape or not np.array_equal(state[name], value)
    ]
    return messages, not_loaded


def behaviour_check(original, extended, mapping: list[int], decoders: dict, strategies: dict) -> dict:
    """Compare the original model with the migrated one on every exported crop."""
    import cv2
    import numpy as np
    import paddle
    from paddlex.inference.models.text_recognition.processors import OCRReisizeNormImg

    resize = OCRReisizeNormImg(rec_image_shape=[3, 48, 320])
    manifest = bakeoff.load_manifest()
    inference = bakeoff.load_predictions(bakeoff.PREDICTION_FILES[bakeoff.PPOCR])
    added = sorted(set(range(extended.head.ctc_head.fc.weight.shape[1])) - set(mapping))

    feature_gap = logit_gap = 0.0
    same_as_inference = 0
    unchanged = dict.fromkeys(strategies, 0)
    new_class_steps = dict.fromkeys(strategies, 0)
    with paddle.no_grad():
        for row in manifest:
            image = cv2.imread(str(bakeoff.verified_crop_path(row)), cv2.IMREAD_COLOR)
            batch = paddle.to_tensor(resize([image])[0][np.newaxis])
            # Encoder output, then the CTC logits before the eval-mode softmax.
            old_features = original.head.ctc_encoder(original.backbone(batch))
            new_features = extended.head.ctc_encoder(extended.backbone(batch))
            old_logits = original.head.ctc_head.fc(old_features).numpy()
            new_logits = extended.head.ctc_head.fc(new_features).numpy()
            feature_gap = max(feature_gap, float(paddle.abs(old_features - new_features).max()))
            logit_gap = max(logit_gap, float(np.abs(new_logits[..., mapping] - old_logits).max()))

            old_text = decoders["original"](old_logits)[0][0]
            same_as_inference += old_text == inference[row["id"]]["prediction"]
            features = old_features.numpy()
            for name, (weight, bias) in strategies.items():
                logits = features @ weight + bias
                unchanged[name] += decoders["extended"](logits)[0][0] == old_text
                new_class_steps[name] += int(np.isin(logits.argmax(-1), added).sum())
    return {
        "crops": len(manifest),
        "max_feature_difference": feature_gap,
        "max_old_class_logit_difference": logit_gap,
        "checkpoint_matches_inference_model": same_as_inference,
        "new_row_initialisation": {
            name: {
                "crops_with_unchanged_text": unchanged[name],
                "time_steps_won_by_a_new_class": new_class_steps[name],
            }
            for name in strategies
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--checkpoint", type=Path, default=CHECKPOINT)
    parser.add_argument("--results-dir", type=Path, default=bakeoff.RESULTS_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.checkpoint.is_file():
        raise SystemExit(f"Missing training checkpoint: {args.checkpoint}\nDownload {CHECKPOINT_URL}")
    if bakeoff.sha256_file(args.checkpoint) != CHECKPOINT_SHA256:
        raise SystemExit(f"{args.checkpoint} is not the file this analysis was written for.")

    # The vendored tree is only read: keep even bytecode files out of it.
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(VENDOR_DIR))
    warnings.simplefilter("ignore", SyntaxWarning)  # docstrings in the vendored heads
    import numpy as np
    import paddle
    import yaml

    codecs = load_rec_postprocess()
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    use_space_char = config["Global"]["use_space_char"]
    if (VENDOR_DIR / config["Global"]["character_dict_path"]).resolve() != PPOCRV6_DICT.resolve():
        raise SystemExit("The training config does not use ppocrv6_dict.txt.")
    classes = {
        "original": class_lists(codecs, PPOCRV6_DICT, use_space_char),
        "extended": class_lists(codecs, EXTENDED_DICT, use_space_char),
    }

    checkpoint = paddle.load(str(args.checkpoint), return_numpy=True)
    paddle.seed(0)
    original = build(config, len(classes["original"]["ctc"]))
    extended = build(config, len(classes["extended"]["ctc"]))
    original_shapes, extended_shapes = shapes(original.state_dict()), shapes(extended.state_dict())

    print(f"checkpoint: {args.checkpoint.name} ({args.checkpoint.stat().st_size} bytes)")
    print(f"tensors: {len(checkpoint)}, parameters: {sum(v.size for v in checkpoint.values())}")
    print(f"use_space_char: {use_space_char}")
    fits = shapes(checkpoint) == original_shapes
    print(f"1. checkpoint fits the model built from {CONFIG.name}: {'yes' if fits else 'NO'}")
    if not fits:
        raise SystemExit("The checkpoint and the config disagree; the analysis below would be wrong.")

    dependent = [name for name in original_shapes if original_shapes[name] != extended_shapes[name]]
    print(f"2. tensors whose shape depends on the dictionary: {len(dependent)}")
    for name in dependent:
        print(f"   {name}: {original_shapes[name]} -> {extended_shapes[name]}")
    kept = [name for name in original_shapes if name not in dependent]
    print(
        f"   unchanged tensors: {len(kept)} (backbone "
        f"{sum(name.startswith('backbone.') for name in kept)}, "
        f"head {sum(name.startswith('head.') for name in kept)})"
    )

    mappings = {}
    print("3. class positions, original -> extended dictionary")
    for head in ("ctc", "nrtr"):
        old, new = classes["original"][head], classes["extended"][head]
        mappings[head] = index_map(old, new)
        moved = [(index, target) for index, target in enumerate(mappings[head]) if index != target]
        added = sorted(set(range(len(new))) - set(mappings[head]))
        print(
            f"   {head}: {len(old)} -> {len(new)} classes; {len(old) - len(moved)} keep their "
            f"index; new classes at {added[0]}..{added[-1]}"
        )
        for index, target in moved:
            print(f"      moves: {old[index]!r} from {index} to {target}")

    messages, not_loaded = loader_report(
        build(config, len(classes["extended"]["ctc"])), args.checkpoint, checkpoint
    )
    print(
        f"4. vendored load_pretrained_params on the extended model: {len(messages)} warning(s), "
        f"{len(not_loaded)} tensor(s) left at their random initialisation"
    )
    for message in messages:
        print(f"   {message}")
    skipped_are_dependent = sorted(not_loaded) == sorted(dependent)
    print(f"   skipped tensors are exactly the dictionary-dependent ones: "
          f"{'yes' if skipped_are_dependent else 'NO'}")

    fresh = {name: value.numpy() for name, value in extended.state_dict().items()}
    head_of = {name: "nrtr" if ".gtc_head." in name else "ctc" for name in dependent}
    migrated = {
        name: migrate(value, fresh[name], mappings[head_of[name]]) if name in dependent else value
        for name, value in checkpoint.items()
    }
    extended.set_state_dict({name: paddle.to_tensor(value) for name, value in migrated.items()})
    original.set_state_dict({name: paddle.to_tensor(value) for name, value in checkpoint.items()})
    decoders = {
        "original": codecs.CTCLabelDecode(str(PPOCRV6_DICT), use_space_char),
        "extended": codecs.CTCLabelDecode(str(EXTENDED_DICT), use_space_char),
    }
    strategies = new_row_strategies(
        migrated[CTC_WEIGHT], migrated[CTC_BIAS], classes["original"]["ctc"], classes["extended"]["ctc"]
    )
    behaviour = behaviour_check(original, extended, mappings["ctc"], decoders, strategies)
    crops = behaviour["crops"]
    print(f"5. in-memory migration, checked on {crops} line crops")
    print(f"   largest difference in encoder features:      {behaviour['max_feature_difference']:.3g}")
    print(f"   largest difference in logits of old classes: {behaviour['max_old_class_logit_difference']:.3g}")
    print(f"   checkpoint decodes like the inference model: "
          f"{behaviour['checkpoint_matches_inference_model']}/{crops}")
    print("6. initial values of the new CTC rows, before any training")
    for name, result in behaviour["new_row_initialisation"].items():
        print(
            f"   {name}: text unchanged on {result['crops_with_unchanged_text']}/{crops} crops, "
            f"{result['time_steps_won_by_a_new_class']} time step(s) won by a new class"
        )

    write_csv(
        args.results_dir / "ppocrv6_medium_rec_state_dict.csv",
        STATE_DICT_COLUMNS,
        [
            {
                "name": name,
                "shape": "x".join(map(str, shape)),
                "parameters": int(np.prod(shape)),
                "vocabulary_dependent": name in dependent,
                "shape_with_extended_dict": "x".join(map(str, extended_shapes[name])),
            }
            for name, shape in original_shapes.items()
        ],
    )
    bakeoff.write_json(
        args.results_dir / "ppocrv6_head_analysis.json",
        {
            "checkpoint_url": CHECKPOINT_URL,
            "checkpoint_sha256": CHECKPOINT_SHA256,
            "config": str(CONFIG.relative_to(bakeoff.REPO_ROOT)),
            "use_space_char": use_space_char,
            "tensors": len(checkpoint),
            "parameters": int(sum(v.size for v in checkpoint.values())),
            "classes": {
                name: {head: len(characters) for head, characters in lists.items()}
                for name, lists in classes.items()
            },
            "vocabulary_dependent_tensors": {
                name: {"original": original_shapes[name], "extended": extended_shapes[name]}
                for name in dependent
            },
            "moved_classes": {
                head: [
                    {"character": classes["original"][head][index], "from": index, "to": target}
                    for index, target in enumerate(mapping)
                    if index != target
                ]
                for head, mapping in mappings.items()
            },
            "loader_warnings": messages,
            "loader_skipped_tensors": sorted(not_loaded),
            "loader_skips_exactly_the_dependent_tensors": skipped_are_dependent,
            "migration_check": behaviour,
        },
    )
    print(f"wrote {args.results_dir}/ppocrv6_medium_rec_state_dict.csv, ppocrv6_head_analysis.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())

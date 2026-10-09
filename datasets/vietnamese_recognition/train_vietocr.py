#!/usr/bin/env python3
"""Fine-tune VietOCR for one experiment config, keeping the weights that read real validation lines best.

Usage (VietOCR environment, ``.venv-vietocr``):
    python datasets/vietnamese_recognition/train_vietocr.py \\
        --config configs/vietnamese/vietocr/exp_a_width512.yml --smoke --device cpu \\
        --batch-size 4 --accumulation-steps 4
    python datasets/vietnamese_recognition/train_vietocr.py \\
        --config configs/vietnamese/vietocr/exp_a_width512.yml            # the full run, on a GPU
    python datasets/vietnamese_recognition/train_vietocr.py --config ... --resume

Why this script exists instead of a call to ``vietocr.model.trainer.Trainer``.
The pinned trainer keeps the weights with the best full-line accuracy, decodes
its validation with 128 steps whatever the config says, sets no random seed,
cannot accumulate gradients, saves no scheduler state, and needs LMDB,
albumentations and matplotlib merely to be imported. None of that can be
changed without editing the checkout, which stays untouched.

What is VietOCR's own, called as it is:

    the network            ``vietocr.tool.translate.build_model``
    the vocabulary         ``vietocr.model.vocab.Vocab``
    image preprocessing    ``vietocr.tool.translate.process_image`` and ``resize``
    the loss               ``vietocr.optim.labelsmoothingloss.LabelSmoothingLoss``
    greedy decoding        ``vietocr.tool.translate.translate``, through ``run_vietocr.recognise``

What mirrors the pinned trainer, line for line where it matters:

    optimizer    AdamW(betas=(0.9, 0.98), eps=1e-09)
    schedule     OneCycleLR(total_steps=trainer.iters, **optimizer)
    one step     forward, label-smoothing loss (0.1), clip the gradient norm at 1,
                 optimizer step, scheduler step
    batches      lines of one resized width per batch, incomplete batches of a
                 width left out for that pass (``ClusterRandomSampler``)
    collation    padding and the 5% random token masking of ``Collator``

What it adds:

    seeds        Python, NumPy and PyTorch are seeded from ``experiment.seed``;
                 batch order and token masks are functions of the seed and of
                 the batch number, so they do not depend on worker processes
    selection    after every ``trainer.valid_every`` steps the real validation
                 lines are read with the project decoder; the weights with the
                 lowest CER (NFC), then the lowest WER, are kept. Synthetic
                 validation lines are read too, as a diagnostic that selects
                 nothing. The blind test is never opened.
    accumulation ``trainer.batch_size`` lines per forward pass, gradients of
                 ``experiment.accumulation_steps`` passes summed per step
    state        ``checkpoint.pth`` holds everything needed to resume: weights,
                 optimizer, scheduler, random state, history

Batch normalisation. The backbone is VGG19 with batch-norm layers. In training
mode, as the pinned trainer runs them, they normalise with the statistics of
the lines in the current forward pass and overwrite their stored statistics
with a moving average of those. Both depend on the number of lines per forward
pass, and accumulating gradients does not change that: four passes of 4 lines
are not one pass of 16 to a batch-norm layer. Two consequences:

    - experiments that are to differ in width only must use the same
      ``trainer.batch_size``, not merely the same effective batch. A run
      refuses to start when the other experiment used another one;
    - with few lines per pass the stored statistics drift quickly. After 20
      steps of 4 lines at a learning rate of 4e-6 the weights had moved by
      0.03% and the statistics by 34%, and line accuracy on real validation
      lines fell from 56% to 32%; with the pretrained statistics put back the
      same weights read 58%.

The experiments therefore run with ``experiment.batch_norm_statistics: frozen``.
What that means, exactly:

    - every batch-norm layer is in evaluation mode during training: it
      normalises with the running mean and variance stored in the pretrained
      checkpoint, never with those of the current batch;
    - those stored statistics, and the counter of batches seen, do not change;
    - the scale and shift of the layer (gamma, beta) are parameters like any
      other: they receive gradients and are updated by the optimizer;
    - nothing else is frozen: the convolutions of the backbone and the whole
      transformer are trained, and dropout is active.

With ``updated`` the layers behave as in the pinned trainer. The policy is
part of the config, so both experiments have it; ``--freeze-batch-norm-statistics``
forces ``frozen`` whatever the config says. A smoke run checks that the
statistics are still those of the pretrained checkpoint and that gamma and
beta have moved.

Files written under ``trainer.export``'s directory (``smoke/`` below it for a smoke run):

    weights.pth      weights with the best real-validation CER so far
    last.pth         weights after the latest validated step
    checkpoint.pth   full training state at that step
    report.json      settings, input digests, every validation, the selection
    train.log

A smoke run is the first steps of the real schedule with every check switched
on. It proves the run works; its numbers say nothing about the result.

``--probe-memory`` trains nothing that is kept: it runs a few optimizer steps
on the most demanding batches a run can meet (the widest lines with the longest
labels), reports the peak memory, and exits with status 3 when the device ran
out of memory. ``probe_cuda_batch.py`` uses it to find the batch size.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import yaml

import dataset_common as dataset
import training_inputs
from build_vietocr_config import supported_label_characters
from dataset_common import REAL_VAL, SYNTHETIC_VAL

import evaluate_splits  # noqa: E402  (path set up by dataset_common)
import run_vietocr  # noqa: E402

SELECTION_KEYS = ("cer_nfc", "wer_nfc")
MASK_SHARE = 0.05  # of the label tokens, as in vietocr.loader.dataloader.Collator
MASK_TOKEN, SPECIAL_TOKENS = 3, (0, 1, 2)  # Vocab.mask_token; pad, start, end
LABEL_SMOOTHING = 0.1
GRADIENT_CLIP = 1.0
SMOKE_STEPS = 20
SMOKE_DIAGNOSTIC_LINES = 40
# A run keeps three files of about 150, 150 and 450 MB, and each is written
# next to the one it replaces before taking its place.
DISK_SPACE_NEEDED_MB = 1500
PROBE_STEPS = 3
OUT_OF_MEMORY_STATUS = 3
# Largest difference accepted between the loss of one batch in mixed and in single precision.
AMP_LOSS_TOLERANCE = 0.01


# --- reproducibility ------------------------------------------------------------


def seed_everything(seed: int) -> None:
    import numpy
    import torch

    random.seed(seed)
    numpy.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False


def seed_worker(worker_id: int) -> None:
    """Workers only decode and pad images, but seed them anyway."""
    import numpy
    import torch

    seed = torch.initial_seed() % 2**32
    random.seed(seed)
    numpy.random.seed(seed)


# --- data -----------------------------------------------------------------------


def read_annotation(path: Path) -> list[tuple[str, str]]:
    """``(image path, label)`` per line of a VietOCR annotation file."""
    samples = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        fields = line.split("\t")
        if len(fields) != 2:
            raise SystemExit(f"{path.name}:{number}: expected an image path and a label separated by one tab.")
        samples.append((fields[0], fields[1]))
    return samples


class ClusterBatches:
    """Batches of one image width, as VietOCR's ``ClusterRandomSampler`` forms them.

    Per pass and per width: shuffle the lines, cut them into batches, leave an
    incomplete batch out, then shuffle all batches of the pass. Which lines of
    a width are left out changes from pass to pass.

    The order is a function of the seed and of the pass number, and every pass
    has the same number of batches. Batch number ``k`` of the endless stream is
    therefore known without any state, which is what makes a resumed run read
    exactly the batches an uninterrupted one would have.
    """

    def __init__(self, buckets: dict[int, list[int]], batch_size: int, seed: int, start: int = 0) -> None:
        self.buckets = {width: sorted(indices) for width, indices in sorted(buckets.items())}
        self.batch_size, self.seed, self.start = batch_size, seed, start
        self.batches_per_pass = sum(len(indices) // batch_size for indices in self.buckets.values())
        self.samples_per_pass = self.batches_per_pass * batch_size
        if not self.batches_per_pass:
            raise SystemExit(f"No width has {batch_size} lines: the batch size is too large for this data.")

    def pass_batches(self, number: int) -> list[list[int]]:
        rng = random.Random(f"{self.seed}:{number}")
        batches = []
        for indices in self.buckets.values():
            shuffled = list(indices)
            rng.shuffle(shuffled)
            batches += [shuffled[i : i + self.batch_size] for i in range(0, len(shuffled) - self.batch_size + 1, self.batch_size)]
        rng.shuffle(batches)
        return batches

    def batch(self, number: int) -> list[int]:
        return self.pass_batches(number // self.batches_per_pass)[number % self.batches_per_pass]

    def __iter__(self):
        number = self.start
        while True:
            current = self.pass_batches(number // self.batches_per_pass)
            for batch in current[number % self.batches_per_pass :]:
                yield batch
                number += 1


class LineDataset:
    """One training line: the image as VietOCR's ``OCRDataset.read_data`` prepares it, and its encoded label."""

    def __init__(self, root: Path, samples: list[tuple[str, str]], vocab, sizes: dict) -> None:
        self.root, self.samples, self.vocab, self.sizes = root, samples, vocab, sizes

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int) -> dict:
        from PIL import Image
        from vietocr.tool.translate import process_image

        relative, label = self.samples[index]
        path = self.root / relative
        with Image.open(path) as image:
            pixels = process_image(image.convert("RGB"), self.sizes["image_height"], self.sizes["image_min_width"], self.sizes["image_max_width"])
        return {"img": pixels, "word": self.vocab.encode(label), "img_path": str(path)}


def width_buckets(root: Path, samples: list[tuple[str, str]], sizes: dict) -> dict[int, list[int]]:
    """Sample indices by the width VietOCR's ``resize`` gives their image."""
    from PIL import Image
    from vietocr.tool.translate import resize

    known: dict[str, int] = {}
    buckets: dict[int, list[int]] = {}
    for index, (relative, _) in enumerate(samples):
        if relative not in known:
            with Image.open(root / relative) as image:
                width, height = image.size
            known[relative] = resize(width, height, sizes["image_height"], sizes["image_min_width"], sizes["image_max_width"])[0]
        buckets.setdefault(known[relative], []).append(index)
    return buckets


def collate(batch: list[dict]) -> dict:
    """VietOCR's ``Collator.__call__`` without its random masking (see ``mask_tokens``)."""
    import numpy as np
    import torch

    filenames, img, target_weights, tgt_input = [], [], [], []
    max_label_len = max(len(sample["word"]) for sample in batch)
    for sample in batch:
        img.append(sample["img"])
        filenames.append(sample["img_path"])
        label = sample["word"]
        label_len = len(label)
        tgt_input.append(np.concatenate((label, np.zeros(max_label_len - label_len, dtype=np.int32))))
        one_mask_len = label_len - 1
        target_weights.append(
            np.concatenate((np.ones(one_mask_len, dtype=np.float32), np.zeros(max_label_len - one_mask_len, dtype=np.float32)))
        )
    img = np.array(img, dtype=np.float32)
    tgt_input = np.array(tgt_input, dtype=np.int64).T
    tgt_output = np.roll(tgt_input, -1, 0).T
    tgt_output[:, -1] = 0
    tgt_padding_mask = np.array(target_weights) == 0
    return {
        "img": torch.FloatTensor(img),
        "tgt_input": torch.LongTensor(tgt_input),
        "tgt_output": torch.LongTensor(tgt_output),
        "tgt_padding_mask": torch.BoolTensor(tgt_padding_mask),
        "filenames": filenames,
    }


def mask_tokens(tgt_input, seed: int, batch_number: int) -> int:
    """Replace 5% of the label tokens by the mask token, in place; returns how many.

    The masking of ``Collator``, drawn from a generator that depends on the
    seed and the batch number only. It runs in the main process, after the
    batch is collated, so the masks are the same with any number of workers.
    """
    import numpy as np
    import torch

    rng = np.random.RandomState([seed % 2**32, batch_number])
    mask = torch.from_numpy(rng.random_sample(size=tuple(tgt_input.shape)) < MASK_SHARE)
    for token in SPECIAL_TOKENS:
        mask &= tgt_input != token
    tgt_input[mask] = MASK_TOKEN
    return int(mask.sum())


# --- model ----------------------------------------------------------------------


def load_pretrained(model, path: Path, device: str) -> dict:
    """Load the checkpoint as ``Trainer.load_weights`` does, and say what was loaded."""
    import torch

    state = torch.load(path, map_location=torch.device(device))
    parameters = dict(model.named_parameters())
    missing = [name for name in parameters if name not in state]
    mismatched = [name for name, value in parameters.items() if name in state and state[name].shape != value.shape]
    model.load_state_dict({key: value for key, value in state.items() if key not in mismatched}, strict=False)
    identical = sum(torch.equal(value.detach().cpu(), state[name].cpu()) for name, value in model.named_parameters() if name in state)
    return {
        "file": path.name,
        "parameter_tensors": len(parameters),
        "missing": len(missing),
        "shape_mismatch": len(mismatched),
        "identical_to_checkpoint": identical,
        "loaded": not missing and not mismatched and identical == len(parameters),
    }


def read_lines(model, vocab, config: dict, rows: list[dict], root: Path, max_seq_length: int) -> dict:
    """Read the lines of one set with the project decoder and score them."""
    from PIL import Image

    predictor = SimpleNamespace(config=config, model=model, vocab=vocab)
    predictions, hits = {}, 0
    started = time.perf_counter()
    for row in rows:
        with Image.open(root / row["image_path"]) as image:
            text, _, _, hit_limit = run_vietocr.recognise(predictor, image, max_seq_length)
        predictions[row["id"]] = text
        hits += bool(hit_limit)
    result = evaluate_splits.score_rows(rows, predictions)
    result.update(decoder_limit_hits=hits, seconds=round(time.perf_counter() - started, 1))
    return result


def selection_key(result: dict) -> tuple[float, float]:
    return tuple(result[key] for key in SELECTION_KEYS)


def is_better(candidate: dict, best: dict | None) -> bool:
    """Lower real-validation CER wins; on a tie, lower WER. Nothing else is looked at."""
    return best is None or selection_key(candidate) < selection_key(best)


# --- settings and checks ----------------------------------------------------------


def resolve_settings(config: dict, args: argparse.Namespace) -> dict:
    """What this run does, from the config and the few things the command line may change."""
    experiment, trainer = config["experiment"], config["trainer"]
    schedule = experiment["schedule"]
    effective = schedule["effective_batch_size"]
    batch_size = args.batch_size or trainer["batch_size"]
    accumulation = args.accumulation_steps or (experiment["accumulation_steps"] if args.batch_size is None else effective // batch_size)
    if batch_size * accumulation != effective:
        raise SystemExit(
            f"batch size {batch_size} x accumulation {accumulation} = {batch_size * accumulation}, but the experiment is "
            f"defined with an effective batch of {effective}. Change both so that their product stays {effective}."
        )
    if trainer["iters"] != schedule["total_steps"] or trainer["valid_every"] != schedule["validate_every"]:
        raise SystemExit("trainer.iters / valid_every disagree with experiment.schedule: run build_vietocr_config.py.")
    if experiment.get("batch_norm_statistics", "updated") not in ("frozen", "updated"):
        raise SystemExit(f"experiment.batch_norm_statistics must be frozen or updated, not {experiment['batch_norm_statistics']!r}.")
    steps = schedule["total_steps"]
    if args.smoke:
        steps = min(args.steps or SMOKE_STEPS, steps)
    elif args.steps:
        raise SystemExit("--steps shortens a smoke run only; a full run follows the schedule of the config.")
    return {
        "experiment": experiment["name"],
        "mode": "probe" if args.probe_memory else "smoke" if args.smoke else "full",
        "seed": experiment["seed"],
        "image_height": config["dataset"]["image_height"],
        "image_max_width": config["dataset"]["image_max_width"],
        "decoder_max_seq_length": config["decoder_max_seq_length"],
        "physical_batch_size": batch_size,
        "accumulation_steps": accumulation,
        "effective_batch_size": effective,
        "steps": steps,
        "scheduled_steps": schedule["total_steps"],
        "validate_every": schedule["validate_every"],
        "max_lr": config["optimizer"]["max_lr"],
        "pct_start": config["optimizer"]["pct_start"],
        "masked_language_model": config["aug"]["masked_language_model"],
        "image_aug": config["aug"]["image_aug"],
        "mixed_precision": bool(args.amp),
        "batch_norm_statistics": "frozen" if args.freeze_batch_norm_statistics else experiment.get("batch_norm_statistics", "updated"),
        "device": args.device or config["device"],
        "num_workers": config["dataloader"]["num_workers"] if args.num_workers is None else args.num_workers,
    }


def output_directory(config: dict, run_name: str | None) -> Path:
    """Where a run writes: the folder of ``trainer.export``, or a named folder below it for a smoke run."""
    directory = (dataset.REPO_ROOT / config["trainer"]["export"]).parent
    return directory / run_name if run_name else directory


# What two experiments must have in common for their results to be compared.
COMMON_SETTINGS = {"seed": None, "physical_batch_size": None, "accumulation_steps": None, "effective_batch_size": None,
                   "scheduled_steps": None, "validate_every": None, "max_lr": None, "pct_start": None,
                   "decoder_max_seq_length": None, "image_height": None, "masked_language_model": None, "image_aug": None,
                   "mixed_precision": False, "batch_norm_statistics": "updated"}  # fmt: skip


def unequal_settings(first: dict, second: dict) -> list[str]:
    """Settings in which two runs differ although experiments have to share them."""
    return [
        f"{key}: {first.get(key, default)} and {second.get(key, default)}"
        for key, default in COMMON_SETTINGS.items()
        if first.get(key, default) != second.get(key, default)
    ]


def check_inputs(config_path: Path, config: dict, vocab, samples: list[tuple[str, str]], run_name: str | None, settings: dict) -> dict:
    """Everything that must hold before a gradient is computed. Stops the run otherwise."""
    recorded, found = training_inputs.load(), training_inputs.current()
    if config_path.name not in found["configs"] or config_path.name not in recorded["configs"]:
        raise SystemExit(f"STOP: {config_path.name} is not one of the experiment configs recorded in training_inputs.json.")
    changed = training_inputs.differences(recorded, found, training_inputs.SHARED)
    if recorded["configs"][config_path.name]["sha256"] != found["configs"][config_path.name]["sha256"]:
        changed.append(f"configs/{config_path.name}: differs from the recorded file")
    if changed:
        raise SystemExit("STOP: training inputs differ from manifests/training_inputs.json:\n  " + "\n  ".join(changed))

    # The other experiment must have read the very same data, in the very same way.
    for sibling in sorted(output_directory(config, None).parent.glob("*/")):
        report = (sibling / run_name if run_name else sibling) / "report.json"
        if report.is_file() and sibling.name != config["experiment"]["name"]:
            other = json.loads(report.read_text(encoding="utf-8"))
            differing = training_inputs.differences(other["digests"], found, training_inputs.SHARED)
            if differing:
                raise SystemExit(f"STOP: the data differ from what {sibling.name} was run on:\n  " + "\n  ".join(differing))
            unequal = unequal_settings(other["settings"], settings)
            if unequal:
                raise SystemExit(f"STOP: {sibling.name} was run with other settings; the experiments may differ in width only:\n  " + "\n  ".join(unequal))

    data_root = dataset.REPO_ROOT / config["dataset"]["data_root"]
    files = {key: data_root / config["dataset"][key] for key in ("train_annotation", "valid_annotation")}
    # Only the manifests of the training and validation sets are opened here.
    leaks = dataset.training_data_problems(files["train_annotation"], files["valid_annotation"], data_root, dataset.LEARNING_SPLITS)
    if leaks:
        raise SystemExit("STOP: a training or validation file reads lines it must not:\n  " + "\n  ".join(leaks))

    limit = supported_label_characters(config)
    unencodable = [image for image, label in samples if set(label) - set(vocab.c2i)]
    too_long = [image for image, label in samples if len(label) > limit]
    if unencodable or too_long:
        raise SystemExit(f"STOP: {len(unencodable)} training label(s) outside the vocabulary, {len(too_long)} longer than {limit} characters.")
    outside = {
        row["image_path"]
        for split in dataset.TRAINING_SPLITS
        for row in dataset.read_manifest(dataset.manifest_path(split, data_root))
        if row["subset"] == "out_of_vocabulary"
    }
    return {
        "digests": found,
        "training_samples": len(samples),
        "distinct_training_images": len({image for image, _ in samples}),
        "labels_outside_vocabulary": len(unencodable),
        "out_of_vocabulary_lines_in_training": len(outside & {image for image, _ in samples}),
        "longest_training_label": max(len(label) for _, label in samples),
        "supported_label_characters": limit,
        "lines_outside_the_training_and_validation_sets": len(leaks),
        "manifests_opened": sorted(dataset.LEARNING_SPLITS),
    }


# --- state ------------------------------------------------------------------------


def check_disk_space(directory: Path) -> int:
    """Free megabytes where the run writes; stops the run when it could not save its state."""
    existing = next(parent for parent in (directory, *directory.parents) if parent.exists())
    free = shutil.disk_usage(existing).free // 1024**2
    if free < DISK_SPACE_NEEDED_MB:
        raise SystemExit(f"STOP: {free} MB free at {existing}; a run needs about {DISK_SPACE_NEEDED_MB} MB for its weights and its checkpoint.")
    return free


def save_atomically(value, path: Path) -> None:
    import torch

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    torch.save(value, temporary)
    os.replace(temporary, path)


def training_state(step: int, model, optimizer, scheduler, scaler, record: dict) -> dict:
    import torch

    return {
        "step": step,
        "model": model.state_dict(),
        "optimizer": optimizer.state_dict(),
        "scheduler": scheduler.state_dict(),
        "scaler": scaler.state_dict() if scaler is not None else None,
        "torch_rng": torch.get_rng_state(),
        "cuda_rng": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None,
        "record": record,
    }


def restore_state(state: dict, model, optimizer, scheduler, scaler) -> None:
    import torch

    model.load_state_dict(state["model"])
    optimizer.load_state_dict(state["optimizer"])
    scheduler.load_state_dict(state["scheduler"])
    if scaler is not None and state["scaler"] is not None:
        scaler.load_state_dict(state["scaler"])
    torch.set_rng_state(state["torch_rng"])
    if state["cuda_rng"] is not None and torch.cuda.is_available():
        torch.cuda.set_rng_state_all(state["cuda_rng"])


def write_report(directory: Path, record: dict) -> None:
    dataset.write_text_atomic(directory / "report.json", json.dumps(record, ensure_ascii=False, indent=2) + "\n")


def peak_memory_mb(device: str) -> dict:
    """Peak process RSS plus CUDA allocator peaks, using only stdlib + torch.

    The resource module is POSIX-only, so Windows uses GetProcessMemoryInfo via ctypes.
    """
    import torch

    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        process = kernel32.GetCurrentProcess()
        if not psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        process_peak_rss_mb = round(counters.PeakWorkingSetSize / 1024**2, 1)
    else:
        import resource

        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        process_peak_rss_mb = round(rss / (1024**2 if sys.platform == "darwin" else 1024), 1)

    memory = {"process_peak_rss_mb": process_peak_rss_mb}
    if device.startswith("cuda"):
        memory["cuda_peak_allocated_mb"] = round(torch.cuda.max_memory_allocated() / 1024**2, 1)
        memory["cuda_peak_reserved_mb"] = round(torch.cuda.max_memory_reserved() / 1024**2, 1)
    return memory


# --- the run ----------------------------------------------------------------------


def build(config: dict, settings: dict):
    """The network, its vocabulary, and the optimizer, schedule and loss of the pinned trainer."""
    from torch.optim import AdamW
    from torch.optim.lr_scheduler import OneCycleLR
    from vietocr.optim.labelsmoothingloss import LabelSmoothingLoss
    from vietocr.tool.translate import build_model

    model, vocab = build_model(config)
    optimizer = AdamW(model.parameters(), betas=(0.9, 0.98), eps=1e-09)
    scheduler = OneCycleLR(optimizer, total_steps=settings["scheduled_steps"], **config["optimizer"])
    criterion = LabelSmoothingLoss(len(vocab), padding_idx=vocab.pad, smoothing=LABEL_SMOOTHING)
    return model, vocab, optimizer, scheduler, criterion


def freeze_batch_norm_statistics(model) -> int:
    """Put every batch-norm layer in evaluation mode; returns how many there are.

    Such a layer normalises with its stored statistics and leaves them as they
    are. Its scale and shift remain parameters and are trained like the rest.
    """
    from torch.nn.modules.batchnorm import _BatchNorm

    layers = [module for module in model.modules() if isinstance(module, _BatchNorm)]
    for layer in layers:
        layer.eval()
    return len(layers)


def optimizer_step(
    model, criterion, optimizer, scheduler, scaler, batches: list[dict], device: str,
    count_gradients: bool = False, freeze_statistics: bool = False,
) -> dict:  # fmt: skip
    """One optimizer step over ``len(batches)`` forward passes: ``Trainer.step``, with accumulation."""
    import torch

    model.train()
    if freeze_statistics:
        freeze_batch_norm_statistics(model)
    optimizer.zero_grad()
    losses = []
    for batch in batches:
        img = batch["img"].to(device, non_blocking=True)
        tgt_input = batch["tgt_input"].to(device, non_blocking=True)
        tgt_output = batch["tgt_output"].to(device, non_blocking=True)
        tgt_padding_mask = batch["tgt_padding_mask"].to(device, non_blocking=True)
        with torch.autocast(device_type="cuda" if device.startswith("cuda") else "cpu", enabled=scaler is not None):
            outputs = model(img, tgt_input, tgt_key_padding_mask=tgt_padding_mask)
        # The loss is always computed in single precision.
        loss = criterion(outputs.float().view(-1, outputs.size(2)), tgt_output.view(-1))
        losses.append(loss.item())
        scaled = loss / len(batches)
        (scaler.scale(scaled) if scaler is not None else scaled).backward()
    if scaler is not None:
        scaler.unscale_(optimizer)
    gradient_norm = float(torch.nn.utils.clip_grad_norm_(model.parameters(), GRADIENT_CLIP))
    with_gradient = None
    if count_gradients:
        with_gradient = sum(p.grad is not None and bool(p.grad.abs().sum() > 0) for p in model.parameters())
    if scaler is not None:
        scaler.step(optimizer)
        scaler.update()
    else:
        optimizer.step()
    scheduler.step()
    return {"loss": sum(losses) / len(losses), "gradient_norm": gradient_norm, "tensors_with_gradient": with_gradient}


def worst_case_batches(samples: list[tuple[str, str]], buckets: dict[int, list[int]], batch_size: int, count: int) -> list[list[int]]:
    """The most demanding forward passes of a run: lines of the widest width, longest labels first."""
    widest = max(buckets)
    ordered = sorted(buckets[widest], key=lambda index: (-len(samples[index][1]), index))
    if len(ordered) < batch_size:
        raise SystemExit(f"The widest width has {len(ordered)} line(s): too few for a batch of {batch_size}.")
    batches = [ordered[start : start + batch_size] for start in range(0, len(ordered) - batch_size + 1, batch_size)]
    return [batches[number % len(batches)] for number in range(count)]


def device_report(device: str) -> dict:
    import torch

    report = {"device": device, "torch": torch.__version__}
    if device.startswith("cuda"):
        index = torch.device(device).index or 0
        report.update(
            gpu=torch.cuda.get_device_name(index),
            gpu_memory_mb=round(torch.cuda.get_device_properties(index).total_memory / 1024**2),
            cuda=torch.version.cuda,
            cudnn=torch.backends.cudnn.version(),
        )
    return report


def probe_memory(model, criterion, optimizer, scheduler, scaler, data, samples, buckets, settings: dict) -> dict:
    """Run a few steps on the worst batches and measure; nothing is saved."""
    import torch

    device = settings["device"]
    accumulation, batch_size = settings["accumulation_steps"], settings["physical_batch_size"]
    worst = worst_case_batches(samples, buckets, batch_size, PROBE_STEPS * accumulation)
    result = {
        **device_report(device),
        "experiment": settings["experiment"],
        "image_max_width": settings["image_max_width"],
        "physical_batch_size": batch_size,
        "accumulation_steps": accumulation,
        "effective_batch_size": settings["effective_batch_size"],
        "mixed_precision": settings["mixed_precision"],
        "batch_norm_statistics": settings["batch_norm_statistics"],
        "widest_width": max(buckets),
        "longest_label_in_probe": max(len(samples[index][1]) for batch in worst for index in batch),
        "optimizer_steps": 0,
        "losses": [],
        "out_of_memory": False,
    }
    if device.startswith("cuda"):
        torch.cuda.reset_peak_memory_stats()
    try:
        for step in range(PROBE_STEPS):
            group = [collate([data[index] for index in batch]) for batch in worst[step * accumulation : (step + 1) * accumulation]]
            outcome = optimizer_step(model, criterion, optimizer, scheduler, scaler, group, device,
                                     freeze_statistics=settings["batch_norm_statistics"] == "frozen")  # fmt: skip
            result["losses"].append(outcome["loss"])
            result["optimizer_steps"] += 1
    except RuntimeError as error:  # torch.cuda.OutOfMemoryError is one
        if "out of memory" not in str(error).lower():
            raise
        result["out_of_memory"] = True
    result["loss_finite"] = bool(result["losses"]) and all(math.isfinite(loss) for loss in result["losses"])
    result.update(peak_memory_mb(device))
    return result


def amp_loss_check(model, criterion, batch: dict, device: str) -> dict:
    """The loss of one batch in single and in mixed precision, both without gradients or dropout."""
    import torch

    model.eval()
    img, tgt_input = batch["img"].to(device), batch["tgt_input"].to(device)
    tgt_output, mask = batch["tgt_output"].to(device), batch["tgt_padding_mask"].to(device)
    with torch.no_grad():
        outputs = model(img, tgt_input, tgt_key_padding_mask=mask)
        single = criterion(outputs.float().view(-1, outputs.size(2)), tgt_output.view(-1)).item()
        with torch.autocast(device_type="cuda"):
            outputs = model(img, tgt_input, tgt_key_padding_mask=mask)
        mixed = criterion(outputs.float().view(-1, outputs.size(2)), tgt_output.view(-1)).item()
    difference = abs(single - mixed)
    return {"fp32_loss": single, "amp_loss": mixed, "absolute_difference": difference, "within_tolerance": difference <= AMP_LOSS_TOLERANCE}


def validation_sets(data_root: Path, diagnostic_lines: int | None) -> dict[str, list[dict]]:
    """The lines read at every validation. Only these two manifests are opened; the blind test never is."""
    sets = {split: dataset.read_manifest(dataset.manifest_path(split, data_root)) for split in (REAL_VAL, SYNTHETIC_VAL)}
    if diagnostic_lines is not None:
        sets[SYNTHETIC_VAL] = sets[SYNTHETIC_VAL][:diagnostic_lines]
    return sets


def validate(model, vocab, config: dict, settings: dict, data_root: Path, sets: dict[str, list[dict]]) -> dict:
    """Real validation lines (they select) and synthetic ones (they only inform)."""
    limit = settings["decoder_max_seq_length"]
    return {
        REAL_VAL: read_lines(model, vocab, config, sets[REAL_VAL], data_root, limit),
        SYNTHETIC_VAL: read_lines(model, vocab, config, sets[SYNTHETIC_VAL], data_root, limit) if sets[SYNTHETIC_VAL] else None,
    }


def run(config_path: Path, args: argparse.Namespace) -> dict:
    run_vietocr.check_pinned_checkout()
    sys.dont_write_bytecode = True  # keep the pinned checkout free of bytecode files
    if str(run_vietocr.VIETOCR_DIR) not in sys.path:
        sys.path.insert(0, str(run_vietocr.VIETOCR_DIR))
    import torch
    from torch.utils.data import DataLoader

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    settings = resolve_settings(config, args)
    device = settings["device"]
    if device.startswith("cuda") and not torch.cuda.is_available():
        raise SystemExit(f"The config asks for {device} and this machine has no CUDA. For a smoke run pass --device cpu.")
    if settings["mixed_precision"] and not device.startswith("cuda"):
        raise SystemExit("--amp needs a CUDA device.")
    config["device"] = device
    config["cnn"]["pretrained"] = False  # the checkpoint replaces every weight anyway
    run_name = "probe" if args.probe_memory else (args.run_name or "smoke") if args.smoke else None
    directory = output_directory(config, run_name)
    data_root = dataset.REPO_ROOT / config["dataset"]["data_root"]
    pretrained = dataset.REPO_ROOT / config["pretrain"]
    run_vietocr.check_weights(pretrained, "the URL in third_party/vietocr/config/vgg-transformer.yml")

    if not args.probe_memory:  # a probe writes one small report
        check_disk_space(directory)
    seed_everything(settings["seed"])
    model, vocab, optimizer, scheduler, criterion = build(config, settings)
    scaler = torch.amp.GradScaler("cuda") if settings["mixed_precision"] else None
    samples = read_annotation(data_root / config["dataset"]["train_annotation"])
    checks = check_inputs(config_path, config, vocab, samples, run_name, settings)

    buckets = width_buckets(data_root, samples, config["dataset"])
    record = {
        "settings": settings,
        "digests": checks.pop("digests"),
        "checks": checks,
        "environment": {"torch": torch.__version__, "vietocr_commit": run_vietocr.VIETOCR_COMMIT, "python": sys.version.split()[0]},
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "steps_done": 0,
        "step_losses": [],
        "log": [],
        "validations": [],
        "best": None,
    }
    checkpoint = directory / "checkpoint.pth"
    if args.resume:
        if not checkpoint.is_file():
            raise SystemExit(f"Nothing to resume: {checkpoint} does not exist.")
        state = torch.load(checkpoint, map_location=torch.device(device), weights_only=False)
        for key in ("physical_batch_size", "accumulation_steps", "seed", "image_max_width", "mixed_precision", "scheduled_steps", "batch_norm_statistics"):
            before = state["record"]["settings"].get(key, COMMON_SETTINGS.get(key))
            if before != settings[key]:
                raise SystemExit(f"Cannot resume: {key} was {before} and is now {settings[key]}.")
        changed = training_inputs.differences(state["record"]["digests"], record["digests"])
        if changed:
            raise SystemExit("STOP: the inputs changed since the run was started:\n  " + "\n  ".join(changed))
        restore_state(state, model, optimizer, scheduler, scaler)
        record = state["record"]
        record["settings"]["steps"] = settings["steps"]
    elif checkpoint.exists() and not args.overwrite and not args.probe_memory:
        raise SystemExit(f"{checkpoint} exists. Pass --resume to continue that run or --overwrite to start again.")
    else:
        for stale in ("train.log", "report.json"):  # of the run being started again
            (directory / stale).unlink(missing_ok=True)
        record["pretrained"] = load_pretrained(model, pretrained, device)
        if not record["pretrained"]["loaded"]:
            raise SystemExit(f"STOP: the pretrained checkpoint did not load completely: {record['pretrained']}")
    model = model.to(device)

    sampler = ClusterBatches(buckets, settings["physical_batch_size"], settings["seed"], start=record["steps_done"] * settings["accumulation_steps"])
    record["batches"] = {
        "widths": len(buckets),
        "batches_per_pass": sampler.batches_per_pass,
        "samples_per_pass_in_batches": sampler.samples_per_pass,
        "samples_left_out_per_pass": len(samples) - sampler.samples_per_pass,
        "optimizer_steps_per_pass": round(sampler.batches_per_pass / settings["accumulation_steps"], 1),
    }
    data = LineDataset(data_root, samples, vocab, config["dataset"])
    if args.probe_memory:
        result = probe_memory(model, criterion, optimizer, scheduler, scaler, data, samples, buckets, settings)
        directory.mkdir(parents=True, exist_ok=True)
        name = f"probe_batch{settings['physical_batch_size']}x{settings['accumulation_steps']}.json"
        dataset.write_text_atomic(directory / name, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(
            f"PROBE {settings['experiment']} batch {settings['physical_batch_size']} x {settings['accumulation_steps']}: "
            + ("OUT OF MEMORY" if result["out_of_memory"] else f"ok, losses {[round(loss, 4) for loss in result['losses']]}")
            + f" | peak {result.get('cuda_peak_allocated_mb', result['process_peak_rss_mb'])} MB"
            + (f" allocated, {result['cuda_peak_reserved_mb']} MB reserved of {result['gpu_memory_mb']} MB on {result['gpu']}" if "gpu" in result else " process memory")
            + f" -> {directory / name}",
            flush=True,
        )
        return {"probe": result}
    generator = torch.Generator()
    generator.manual_seed(settings["seed"])
    loader = DataLoader(
        data,
        batch_sampler=sampler,
        collate_fn=collate,
        num_workers=settings["num_workers"],
        pin_memory=bool(config["dataloader"]["pin_memory"]) and device.startswith("cuda"),
        worker_init_fn=seed_worker,
        generator=generator,
    )
    batches = iter(loader)
    log_path = directory / "train.log"
    directory.mkdir(parents=True, exist_ok=True)

    def say(line: str) -> None:
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")

    diagnostic_lines = (args.diagnostic_lines if args.diagnostic_lines is not None else SMOKE_DIAGNOSTIC_LINES) if args.smoke else args.diagnostic_lines
    sets = validation_sets(data_root, diagnostic_lines)

    def validation(step: int) -> None:
        results = validate(model, vocab, config, settings, data_root, sets)
        real = results[REAL_VAL]
        entry = {"step": step, "lr": optimizer.param_groups[0]["lr"], **results}
        record["validations"].append(entry)
        improved = is_better(real, record["best"][REAL_VAL] if record["best"] else None)
        save_atomically(model.state_dict(), directory / "last.pth")
        if improved:
            record["best"] = {"step": step, REAL_VAL: real, SYNTHETIC_VAL: results[SYNTHETIC_VAL], "weights": "weights.pth"}
            save_atomically(model.state_dict(), directory / "weights.pth")
        record["steps_done"] = step
        save_atomically(training_state(step, model, optimizer, scheduler, scaler, record), checkpoint)
        write_report(directory, record)
        synthetic = results[SYNTHETIC_VAL]
        say(
            f"step {step:5d} | real_val CER {real['cer_nfc']:.6f} WER {real['wer_nfc']:.6f} exact {real['exact_line_nfc']:.4f} "
            f"limit hits {real['decoder_limit_hits']} ({real['seconds']} s)"
            + (f" | synthetic_val CER {synthetic['cer_nfc']:.6f} ({synthetic['lines']} lines, diagnostic)" if synthetic else "")
            + (" | BEST so far, saved" if improved else f" | best stays step {record['best']['step']}")
        )

    say(
        f"{settings['experiment']} [{settings['mode']}] on {device}: width {settings['image_max_width']}, batch "
        f"{settings['physical_batch_size']} x accumulation {settings['accumulation_steps']} = {settings['effective_batch_size']}, "
        f"steps {record['steps_done']} -> {settings['steps']} of a {settings['scheduled_steps']}-step schedule, seed {settings['seed']}, "
        f"batch-norm statistics {settings['batch_norm_statistics']}"
    )
    if settings["mixed_precision"] and "amp_check" not in record:
        first = collate([data[index] for index in sampler.batch(0)])
        record["amp_check"] = amp_loss_check(model, criterion, first, device)
        say(f"mixed precision: loss of the first batch {record['amp_check']['amp_loss']:.6f}, in single precision "
            f"{record['amp_check']['fp32_loss']:.6f} (difference {record['amp_check']['absolute_difference']:.2e})")  # fmt: skip
    if record["steps_done"] == 0 and not record["validations"]:
        validation(0)  # the pretrained weights are the first candidate

    window, started = [], time.perf_counter()
    for step in range(record["steps_done"] + 1, settings["steps"] + 1):
        first = (step - 1) * settings["accumulation_steps"]
        group = []
        for offset in range(settings["accumulation_steps"]):
            batch = next(batches)
            if settings["masked_language_model"]:
                mask_tokens(batch["tgt_input"], settings["seed"], first + offset)
            group.append(batch)
        outcome = optimizer_step(
            model, criterion, optimizer, scheduler, scaler, group, device,
            count_gradients=args.smoke, freeze_statistics=settings["batch_norm_statistics"] == "frozen",
        )  # fmt: skip
        if not math.isfinite(outcome["loss"]):
            raise SystemExit(f"STOP: the loss is {outcome['loss']} at step {step}.")
        del record["step_losses"][step - 1 :]  # steps redone after a resume replace what was logged
        record["step_losses"].append(outcome["loss"])
        window.append(outcome)
        if step % config["trainer"]["print_every"] == 0 or step == settings["steps"] or (args.smoke and step <= 3):
            entry = {
                "step": step,
                "loss": sum(o["loss"] for o in window) / len(window),
                "gradient_norm": sum(o["gradient_norm"] for o in window) / len(window),
                "tensors_with_gradient": min(o["tensors_with_gradient"] for o in window) if args.smoke else None,
                "lr": optimizer.param_groups[0]["lr"],
                "seconds_per_step": round((time.perf_counter() - started) / len(window), 3),
            }
            record["log"].append(entry)
            say(f"step {step:5d} | loss {entry['loss']:.4f} | grad norm {entry['gradient_norm']:.3f} | lr {entry['lr']:.3e} | {entry['seconds_per_step']} s/step")
            window, started = [], time.perf_counter()
        if step % settings["validate_every"] == 0 or step == settings["steps"]:
            validation(step)
            started = time.perf_counter()

    record["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    record["memory"] = peak_memory_mb(device)
    record["environment"].update(device_report(device))
    if args.smoke:
        record["smoke"] = smoke_checks(config, settings, directory, model, optimizer, scheduler, pretrained, record)
    write_report(directory, record)
    best = record["best"]
    say(f"best real_val CER {best[REAL_VAL]['cer_nfc']:.6f} (WER {best[REAL_VAL]['wer_nfc']:.6f}) at step {best['step']} -> {directory / 'weights.pth'}")
    return record


def batch_norm_report(model, original: dict) -> dict:
    """How the batch-norm layers of ``model`` compare with the pretrained state ``original``."""
    import torch
    from torch.nn.modules.batchnorm import _BatchNorm

    layers = [(name, module) for name, module in model.named_modules() if isinstance(module, _BatchNorm)]
    statistics_changed = affine_changed = 0
    for name, layer in layers:
        for buffer in ("running_mean", "running_var", "num_batches_tracked"):
            key = f"{name}.{buffer}"
            statistics_changed += key in original and not torch.equal(getattr(layer, buffer).cpu(), original[key].cpu())
        for parameter in ("weight", "bias"):
            affine_changed += not torch.equal(getattr(layer, parameter).detach().cpu(), original[f"{name}.{parameter}"].cpu())
    return {
        "layers": len(layers),
        "statistics_tensors_changed": statistics_changed,
        "running_statistics_unchanged": statistics_changed == 0,
        "affine_tensors": 2 * len(layers),
        "affine_tensors_changed": affine_changed,
        "affine_trainable": all(layer.weight.requires_grad and layer.bias.requires_grad for _, layer in layers),
    }


def smoke_checks(config: dict, settings: dict, directory: Path, model, optimizer, scheduler, pretrained: Path, record: dict) -> dict:
    """What a smoke run has to show before a full run is worth starting."""
    import torch

    device = settings["device"]
    losses = [entry["loss"] for entry in record["log"]]
    original = torch.load(pretrained, map_location="cpu")
    changed = sum(not torch.equal(value.detach().cpu(), original[name]) for name, value in model.named_parameters())
    parameters = sum(1 for _ in model.parameters())
    batch_norm = batch_norm_report(model, original)
    frozen = settings["batch_norm_statistics"] == "frozen"

    # Save and load: the full state into fresh objects, and the kept weights into a fresh network.
    state = torch.load(directory / "checkpoint.pth", map_location=torch.device(device), weights_only=False)
    fresh_model, vocab, fresh_optimizer, fresh_scheduler, _ = build(config, settings)
    restore_state(state, fresh_model, fresh_optimizer, fresh_scheduler, None)
    same_weights = all(torch.equal(a.cpu(), b.cpu()) for a, b in zip(model.state_dict().values(), fresh_model.state_dict().values()))
    same_schedule = (
        fresh_scheduler.last_epoch == scheduler.last_epoch
        and fresh_optimizer.param_groups[0]["lr"] == optimizer.param_groups[0]["lr"]
        and state["step"] == settings["steps"]
    )
    best = record["best"]
    kept_model, _, _, _, _ = build(config, settings)
    kept_model.load_state_dict(torch.load(directory / "weights.pth", map_location=torch.device(device)))
    data_root = dataset.REPO_ROOT / config["dataset"]["data_root"]
    real_val = dataset.read_manifest(dataset.manifest_path(REAL_VAL, data_root))
    again = read_lines(kept_model.to(device), vocab, config, real_val, data_root, settings["decoder_max_seq_length"])
    kept_reads_the_same = selection_key(again) == selection_key(best[REAL_VAL])

    checks = {
        "optimizer_steps": record["steps_done"],
        "loss_first": losses[0],
        "loss_last": losses[-1],
        "loss_finite": all(math.isfinite(loss) for loss in losses),
        "pretrained_weights_loaded": record["pretrained"]["loaded"],
        "gradient_reaches_every_tensor": min(entry["tensors_with_gradient"] for entry in record["log"]) == parameters,
        "parameter_tensors": parameters,
        "tensors_changed_by_training": changed,
        "checkpoint_reload_same_weights": same_weights,
        "checkpoint_reload_same_optimizer_and_schedule": same_schedule,
        "kept_weights_reload_same_real_val_cer": kept_reads_the_same,
        "no_label_outside_vocabulary_in_training": record["checks"]["labels_outside_vocabulary"] == 0
        and record["checks"]["out_of_vocabulary_lines_in_training"] == 0,
        "no_blind_or_regression_line_in_train_or_val_files": record["checks"]["lines_outside_the_training_and_validation_sets"] == 0,
        "evaluation_manifests_never_opened": record["checks"]["manifests_opened"] == sorted(dataset.LEARNING_SPLITS),
        "validations": len(record["validations"]),
        "real_val_read": all(entry[REAL_VAL]["scored_lines"] == entry[REAL_VAL]["lines"] > 0 for entry in record["validations"]),
        "batch_norm": batch_norm,
        # With frozen statistics: untouched, while gamma and beta moved. With updated ones there is nothing to hold.
        "batch_norm_policy_respected": (batch_norm["running_statistics_unchanged"] and batch_norm["affine_tensors_changed"] > 0
                                        and batch_norm["affine_trainable"]) if frozen else True,
    }
    required = ("loss_finite", "pretrained_weights_loaded", "gradient_reaches_every_tensor", "checkpoint_reload_same_weights",
                "checkpoint_reload_same_optimizer_and_schedule", "kept_weights_reload_same_real_val_cer",
                "no_label_outside_vocabulary_in_training", "no_blind_or_regression_line_in_train_or_val_files",
                "evaluation_manifests_never_opened", "real_val_read", "batch_norm_policy_respected")  # fmt: skip
    if settings["mixed_precision"]:
        # Validation is always read in single precision; what mixed precision changes is the training loss.
        checks["mixed_precision_loss_close_to_single_precision"] = record["amp_check"]["within_tolerance"]
        required += ("mixed_precision_loss_close_to_single_precision",)
    checks["result"] = "PASS" if all(checks[name] for name in required) and changed > 0 else "FAIL"
    print(f"SMOKE {checks['result']}: " + ", ".join(f"{name}={checks[name]}" for name in required), flush=True)
    return checks


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, required=True, help="An experiment config (configs/vietnamese/vietocr/exp_*.yml).")
    parser.add_argument("--smoke", action="store_true", help=f"Run the first {SMOKE_STEPS} steps with every check on; outputs go to smoke/.")
    parser.add_argument("--steps", type=int, default=None, help="Optimizer steps of a smoke run.")
    parser.add_argument("--run-name", default=None, help="Folder of a smoke run below the experiment's output folder (default: smoke).")
    parser.add_argument("--device", default=None, help="Default: the device of the config (cuda:0).")
    parser.add_argument("--batch-size", type=int, default=None, help="Lines per forward pass; the effective batch must stay that of the config.")
    parser.add_argument("--accumulation-steps", type=int, default=None, help="Forward passes per optimizer step.")
    parser.add_argument("--num-workers", type=int, default=None, help="Default: dataloader.num_workers of the config.")
    parser.add_argument("--amp", action="store_true", help="Mixed precision on CUDA. Use it for both experiments or for neither.")
    parser.add_argument(
        "--freeze-batch-norm-statistics",
        action="store_true",
        help="Force experiment.batch_norm_statistics = frozen (what the experiment configs already say): keep the "
        "pretrained running mean and variance; gamma and beta stay trainable.",
    )
    parser.add_argument("--diagnostic-lines", type=int, default=None, help="Read only this many synthetic validation lines per validation.")
    parser.add_argument("--probe-memory", action="store_true", help=f"Run {PROBE_STEPS} steps on the worst batches, report peak memory, keep nothing.")
    parser.add_argument("--resume", action="store_true", help="Continue from checkpoint.pth.")
    parser.add_argument("--overwrite", action="store_true", help="Start again although a checkpoint exists.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.probe_memory and (args.smoke or args.resume):
        raise SystemExit("--probe-memory is a run of its own: without --smoke and without --resume.")
    record = run(args.config.resolve(), args)
    if args.probe_memory:
        return OUT_OF_MEMORY_STATUS if record["probe"]["out_of_memory"] else 0
    return 0 if not args.smoke or record["smoke"]["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

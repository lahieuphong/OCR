#!/usr/bin/env python3
"""PP-OCRv6 Vietnamese baseline: run the stock pipeline and save its raw output.

Usage:
    python experiments/vietnamese_baseline/run_ocr.py \
        --input <file-or-directory> \
        --output experiments/vietnamese_baseline/output \
        --device cpu

No correction of any kind is applied to the recognised text. Whatever the
model returns is written out verbatim, so later phases can measure exactly
what the model gets wrong.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

import inspect_environment as env

LANG = "vi"
OCR_VERSION = "PP-OCRv6"
# `lang="vi"` + `ocr_version="PP-OCRv6"` must resolve to exactly these models
# (PaddleOCR/paddleocr/_pipelines/ocr.py::_get_ocr_model_names). They are not
# passed to PaddleOCR() directly, because explicit model names make it ignore
# `lang`/`ocr_version`; instead the resolved pipeline config is checked and the
# run aborts on any mismatch.
DETECTION_MODEL = "PP-OCRv6_medium_det"
RECOGNITION_MODEL = "PP-OCRv6_medium_rec"

SUPPORTED_SUFFIXES = frozenset({".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"})
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "output"
# Per-page files of a previous run, removed before a document is rewritten so
# the output never mixes pages from two runs.
STALE_PAGE_PATTERNS = ("raw/page_*.json", "raw/page_*.png", "visualization/page_*.png")


def str2bool(value: str) -> bool:
    lowered = value.lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"expected a boolean, got {value!r}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the PP-OCRv6 Vietnamese baseline and save raw OCR output."
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="A PDF/image file, or a directory of them (not scanned recursively).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Directory that receives one sub-directory per document.",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        help="Inference device, e.g. `cpu` or `gpu:0`.",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="Optional label for this configuration, recorded in metadata.json.",
    )
    toggles = (
        ("--use-doc-orientation", "document orientation classification"),
        ("--use-doc-unwarping", "document image unwarping"),
        ("--use-textline-orientation", "text line orientation classification"),
    )
    for flag, description in toggles:
        parser.add_argument(
            flag,
            nargs="?",
            const=True,
            default=True,
            type=str2bool,
            metavar="BOOL",
            help=f"Enable {description} (default: true). Pass `false` to disable.",
        )
    return parser.parse_args(argv)


def collect_inputs(input_path: Path) -> list[Path]:
    """Supported files under ``input_path``, in a deterministic order."""
    if input_path.is_file():
        if input_path.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise SystemExit(
                f"Unsupported input type {input_path.suffix!r}. "
                f"Supported: {', '.join(sorted(SUPPORTED_SUFFIXES))}"
            )
        return [input_path]
    if input_path.is_dir():
        return sorted(
            (
                path
                for path in input_path.iterdir()
                if path.is_file()
                and not path.name.startswith(".")
                and path.suffix.lower() in SUPPORTED_SUFFIXES
            ),
            key=lambda path: path.name,
        )
    raise SystemExit(f"Input not found: {input_path}")


def document_names(paths: list[Path]) -> dict[Path, str]:
    """Output directory name per input: the stem, or the full name on a clash."""
    stems = Counter(path.stem for path in paths)
    return {
        path: path.stem if stems[path.stem] == 1 else path.name.replace(".", "_")
        for path in paths
    }


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_text(path: Path, data: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(data)


def write_json(path: Path, data: object) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def check_device(device: str, environment: dict) -> None:
    """Reject a GPU request PaddlePaddle cannot honour.

    PaddleX silently falls back to the CPU in that case, which would leave a
    wrong `device` in metadata.json.
    """
    if device.split(":")[0] == "gpu" and not environment["paddle"]["cuda_device_count"]:
        raise SystemExit(
            f"--device {device} was requested, but this PaddlePaddle build sees no "
            "CUDA device. Use --device cpu."
        )


def create_pipeline(args: argparse.Namespace):
    from paddleocr import PaddleOCR

    return PaddleOCR(
        lang=LANG,
        ocr_version=OCR_VERSION,
        use_doc_orientation_classify=args.use_doc_orientation,
        use_doc_unwarping=args.use_doc_unwarping,
        use_textline_orientation=args.use_textline_orientation,
        device=args.device,
    )


def resolved_pipeline_config(ocr) -> dict:
    """The PaddleX pipeline config PaddleOCR actually built, as a plain dict."""
    import yaml

    with tempfile.TemporaryDirectory() as tmp_dir:
        config_path = Path(tmp_dir) / "paddlex_config.yaml"
        ocr.export_paddlex_config_to_yaml(str(config_path))
        return yaml.safe_load(config_path.read_text(encoding="utf-8"))


def check_baseline_models(config: dict) -> None:
    detection = config["SubModules"]["TextDetection"]["model_name"]
    recognition = config["SubModules"]["TextRecognition"]["model_name"]
    if (detection, recognition) != (DETECTION_MODEL, RECOGNITION_MODEL):
        raise SystemExit(
            f"lang={LANG!r}, ocr_version={OCR_VERSION!r} resolved to "
            f"({detection}, {recognition}); the baseline is locked to "
            f"({DETECTION_MODEL}, {RECOGNITION_MODEL})."
        )


def prepare_document_dir(document_dir: Path) -> None:
    for pattern in STALE_PAGE_PATTERNS:
        for stale in document_dir.glob(pattern):
            stale.unlink()
    (document_dir / "raw").mkdir(parents=True, exist_ok=True)
    (document_dir / "visualization").mkdir(exist_ok=True)


def save_ocr_input_image(result, path: Path) -> bool:
    """Save the image OCR ran on, i.e. the coordinate space of every box.

    With document preprocessing enabled this is the rotated/unwarped page, not
    the original one, and for PDFs it is the rendered page.
    """
    from PIL import Image

    image = result.get("doc_preprocessor_res", {}).get("output_img")
    if image is None:
        return False
    # PaddleX keeps images in OpenCV's BGR channel order.
    Image.fromarray(image[:, :, ::-1]).save(path)
    return True


def timed(results):
    """Yield ``(result, seconds)``: each result and the time spent producing it."""
    iterator = iter(results)
    while True:
        started = time.perf_counter()
        result = next(iterator, None)
        if result is None:
            return
        yield result, time.perf_counter() - started


def process_document(ocr, source: Path, name: str, document_dir: Path) -> dict:
    """Run OCR on one document and write its raw and normalised outputs."""
    prepare_document_dir(document_dir)

    pages = []
    lines = []
    page_stats = []
    # predict_iter() is the streaming form of predict(): only one page is held
    # in memory at a time.
    for position, (result, elapsed) in enumerate(timed(ocr.predict_iter(str(source)))):
        if "error" in result:
            raise RuntimeError(f"{source}: {result['error']}")

        raw = result.json["res"]
        # `page_index` is 0-based for PDFs and None for single images.
        page_index = raw.get("page_index")
        page = page_index + 1 if isinstance(page_index, int) else position + 1
        page_tag = f"page_{page:04d}"

        result.save_to_json(str(document_dir / "raw" / f"{page_tag}.json"))
        save_ocr_input_image(result, document_dir / "raw" / f"{page_tag}.png")
        for key, image in result.img.items():
            image.save(document_dir / "visualization" / f"{page_tag}_{key}.png")

        texts, scores, polygons = raw["rec_texts"], raw["rec_scores"], raw["rec_polys"]
        if not len(texts) == len(scores) == len(polygons):
            raise RuntimeError(
                f"{source} page {page}: mismatched result lengths "
                f"(texts={len(texts)}, scores={len(scores)}, polys={len(polygons)})"
            )
        for line_index, (text, score, polygon) in enumerate(
            zip(texts, scores, polygons)
        ):
            lines.append(
                {
                    "document": name,
                    "page": page,
                    "line_index": line_index,
                    "text": text,
                    "confidence": float(score),
                    "box": polygon,
                }
            )
        pages.append({"page": page, "res": raw})
        page_stats.append(
            {
                "page": page,
                "num_lines": len(texts),
                "elapsed_seconds": round(elapsed, 3),
            }
        )

    write_json(
        document_dir / "result.json",
        {
            "document": name,
            "input_path": str(source),
            "num_pages": len(pages),
            "pages": pages,
        },
    )
    write_text(
        document_dir / "lines.jsonl",
        "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines),
    )
    # One recognised line per text line, pages separated by a form feed.
    write_text(
        document_dir / "text.txt",
        "\f".join(
            "".join(text + "\n" for text in page["res"]["rec_texts"]) for page in pages
        ),
    )
    return {
        "num_pages": len(pages),
        "num_lines": len(lines),
        "elapsed_seconds": round(sum(s["elapsed_seconds"] for s in page_stats), 3),
        "pages": page_stats,
    }


def build_metadata(
    args: argparse.Namespace,
    environment: dict,
    pipeline_config: dict,
    source: Path,
    name: str,
    stats: dict,
) -> dict:
    preprocessor = pipeline_config["SubPipelines"]["DocPreprocessor"]["SubModules"]
    return {
        "profile": args.profile,
        "ocr_version": OCR_VERSION,
        "lang": LANG,
        "detection_model": pipeline_config["SubModules"]["TextDetection"]["model_name"],
        "recognition_model": pipeline_config["SubModules"]["TextRecognition"][
            "model_name"
        ],
        "auxiliary_models": {
            "doc_orientation_classify": preprocessor["DocOrientationClassify"][
                "model_name"
            ],
            "doc_unwarping": preprocessor["DocUnwarping"]["model_name"],
            "textline_orientation": pipeline_config["SubModules"][
                "TextLineOrientation"
            ]["model_name"],
        },
        "device": args.device,
        "repo_commit": environment["repo"]["commit"],
        "repo_branch": environment["repo"]["branch"],
        "repo_dirty": environment["repo"]["dirty"],
        "paddleocr_upstream_snapshot": env.PADDLEOCR_UPSTREAM_SNAPSHOT,
        "paddle_version": environment["paddle"]["version"],
        "paddlex_version": environment["paddlex_version"],
        "paddleocr_version": environment["paddleocr"]["version"],
        "paddleocr_source": environment["paddleocr"]["import_path"],
        "python_version": environment["python"]["version"],
        "platform": environment["platform"]["platform"],
        "configuration": {
            "use_doc_orientation_classify": args.use_doc_orientation,
            "use_doc_unwarping": args.use_doc_unwarping,
            "use_textline_orientation": args.use_textline_orientation,
            "paddlex_pipeline_config": pipeline_config,
        },
        "document": name,
        "input": {
            "path": str(source),
            "sha256": sha256_of(source),
            "size_bytes": source.stat().st_size,
        },
        **stats,
        "timestamp": env.utc_timestamp(),
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    inputs = collect_inputs(args.input)
    if not inputs:
        print(
            f"No supported files in {args.input} "
            f"({', '.join(sorted(SUPPORTED_SUFFIXES))}).",
            file=sys.stderr,
        )
        return 2
    names = document_names(inputs)

    environment = env.collect_environment()
    if not environment["paddleocr"]["is_local_source"]:
        raise SystemExit(
            "paddleocr is not imported from this repository's PaddleOCR/ snapshot "
            f"(found: {environment['paddleocr']['import_path']}). "
            "See experiments/vietnamese_baseline/README.md for the install steps."
        )
    check_device(args.device, environment)

    ocr = create_pipeline(args)
    pipeline_config = resolved_pipeline_config(ocr)
    check_baseline_models(pipeline_config)

    for number, source in enumerate(inputs, start=1):
        name = names[source]
        document_dir = args.output / name
        stats = process_document(ocr, source, name, document_dir)
        # Written last: its presence marks a document that finished cleanly.
        write_json(
            document_dir / "metadata.json",
            build_metadata(args, environment, pipeline_config, source, name, stats),
        )
        print(
            f"[{number}/{len(inputs)}] {source.name}: {stats['num_pages']} page(s), "
            f"{stats['num_lines']} line(s), {stats['elapsed_seconds']}s -> {document_dir}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

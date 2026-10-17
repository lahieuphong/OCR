"""Run crop-geometry configurations with the FROZEN B1024 recognizer on stored polygons.

Run from repo root (Windows CMD):
  .venv-demo\\Scripts\\python.exe -m experiments.crop_geometry.run_experiment ^
    --sources <dir>\\experiment_sources.json --documents 10333 137-vbhn ^
    --output-dir <dir>\\runs\\<new_name>

Detection is NOT rerun: polygons, their order and the page raster come from the
stored export / frozen rerun JSON and the engine's own renderer. Recognizer,
weights, preprocessing and greedy decoding are the frozen ones
(demo.local_pdf_ocr.backend); only the crop changes (experiments/crop_geometry/
geometry.py). Arm A0 must reproduce the stored text of every line or the run
stops. No reference text is read. Results and crops go to a new, git-ignored
directory; nothing existing is overwritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

from .geometry import CONFIGS, crop_line

HERE = Path(__file__).resolve().parent
EXTRA_CONFIGS_NOTE = "B2/C2 added after the geometry analysis (synthetic training margin ~3 px), before any inference"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frozen_recognizer(metadata: dict, threads: int):
    """The website's frozen recognizer; only the ONNX Runtime thread count may differ.

    Many parallel workers with 4 synchronising threads each stall on Windows, so
    the experiment can use 1 thread per process. Graphs, weights, preprocessing
    and decoding are untouched (``predict`` is inherited), and arm A0 must still
    reproduce the stored text of every line.
    """
    from demo.local_pdf_ocr.backend.contract import MODEL_DIR
    from demo.local_pdf_ocr.backend.engine import OnnxVietocrB

    if threads == 4:  # exactly the website's configuration
        return OnnxVietocrB(metadata)
    import onnxruntime as ort

    model = OnnxVietocrB.__new__(OnnxVietocrB)
    model.metadata = metadata
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    model.encoder = ort.InferenceSession(str(MODEL_DIR / "encoder.onnx"), sess_options=options,
                                         providers=["CPUExecutionProvider"])
    model.decoder = ort.InferenceSession(str(MODEL_DIR / "decoder_step.onnx"), sess_options=options,
                                         providers=["CPUExecutionProvider"])
    if (model.encoder.get_inputs()[0].name != "image"
            or {input_.name for input_ in model.decoder.get_inputs()} != {"tokens", "memory"}):
        raise RuntimeError("Unexpected frozen ONNX input signature")
    return model


def select(sources: list[dict], documents: list[str]) -> list[dict]:
    chosen = [s for s in sources if not documents or any(s["document"].startswith(d) for d in documents)]
    if documents and len(chosen) != len(documents):
        raise ValueError(f"STOP: --documents matched {len(chosen)} sources for {len(documents)} names")
    return chosen


def run(sources: list[dict], output_dir: Path, configs, *, save_all_crops_for: set[str] = frozenset(),
        allow_parity_mismatch: bool = False, pages: set[int] | None = None, threads: int = 4) -> dict:
    if output_dir.exists():
        raise ValueError(f"STOP: output already exists (will not overwrite): {output_dir}")
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    import cv2
    import numpy as np
    from PIL import Image

    from demo.local_pdf_ocr.backend.contract import verify_frozen_onnx
    from demo.local_pdf_ocr.backend.engine import iter_images

    metadata = verify_frozen_onnx(require_weights=True)
    recognizer = frozen_recognizer(metadata, threads)
    page_filter = set(pages or ())
    output_dir.mkdir(parents=True)
    (output_dir / "crops").mkdir()
    manifest = {
        "schema": "crop_geometry_run_v1", "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "configs": [c.describe() for c in configs], "configs_note": EXTRA_CONFIGS_NOTE,
        "model": {k: metadata[k] for k in ("selected", "checkpoint_sha256", "encoder_sha256", "decoder_sha256",
                                           "image_height", "image_min_width", "image_max_width",
                                           "decoder_max_seq_length")},
        "inference_provider": "CPUExecutionProvider", "ort_intra_op_threads": threads,
        "code_sha256": {name: sha256_file(HERE / name) for name in ("geometry.py", "run_experiment.py")},
        "python": platform.python_version(),
        "reference_text_used": False, "detection_rerun": False, "blind_set_used": False,
        "sources": [], "parity_mismatches": [],
    }
    results = (output_dir / "results.jsonl").open("w", encoding="utf-8", newline="\n")
    predictions = 0
    try:
        for source in sources:
            pdf = Path(source["pdf"])
            if sha256_file(pdf) != source["pdf_sha256"] or sha256_file(Path(source["ocr_json"])) != source["ocr_json_sha256"]:
                raise ValueError(f"STOP: source changed since the manifest: {source['document']}")
            export = json.loads(Path(source["ocr_json"]).read_text(encoding="utf-8"))
            rasters = dict(iter_images(pdf.read_bytes(), ".pdf"))  # the engine's exact raster
            started, mismatches = time.perf_counter(), []
            for page in export["pages"]:
                if page_filter and page["page"] not in page_filter:
                    continue
                image = rasters[page["page"]]
                if (image.width, image.height) != (page["width"], page["height"]):
                    raise ValueError(f"STOP: raster differs from the export: {source['document']} p{page['page']}")
                bgr = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
                polygons = [line["polygon"] for line in page["lines"]]
                for index, line in enumerate(page["lines"]):
                    key = f"{source['document']}|{page['page']}|{line['line_index']}"
                    neighbours = polygons[:index] + polygons[index + 1:]
                    seen = {}
                    for config in configs:
                        crop, info = crop_line(bgr, line["polygon"], neighbours, config)
                        rgb = np.ascontiguousarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
                        digest = hashlib.sha256(rgb.tobytes() + str(rgb.shape).encode()).hexdigest()
                        if digest in seen:  # identical pixels: the frozen model gives the same text
                            text, limit, reused = *seen[digest][:2], seen[digest][2]
                        else:
                            text, limit = recognizer.predict(Image.fromarray(rgb))
                            seen[digest], reused, predictions = (text, limit, config.name), None, predictions + 1
                        if config.name == "A0" and (text != line["text"] or limit != bool(line.get("hit_decoder_limit"))):
                            mismatches.append({"key": key, "stored": line["text"], "rerun": text})
                        record = {"key": key, "set": source["set"], "document": source["document"], "page": page["page"],
                                  "line_index": line["line_index"], "config": config.name, "text": text,
                                  "hit_decoder_limit": limit, "baseline_text": line["text"],
                                  "crop_hw": list(rgb.shape[:2]), "crop_sha256": digest, "reused_from": reused,
                                  "resize_scale_to_32px": round(32 / rgb.shape[0], 4), **info}
                        results.write(json.dumps(record, ensure_ascii=False) + "\n")
                        if key in save_all_crops_for or (config.name != "A0" and text != line["text"]):
                            name = f"{Path(source['document']).stem}_p{page['page']:03d}_l{line['line_index']:03d}"
                            Image.fromarray(rgb).save(output_dir / "crops" / f"{name}_{config.name}.png")
                            if config.name != "A0":
                                base, _ = crop_line(bgr, line["polygon"], neighbours, configs[0])
                                target = output_dir / "crops" / f"{name}_A0.png"
                                if not target.exists():
                                    Image.fromarray(cv2.cvtColor(base, cv2.COLOR_BGR2RGB)).save(target)
            results.flush()
            manifest["sources"].append({**source, "elapsed_seconds": round(time.perf_counter() - started, 1),
                                        "pages_run": sorted(page_filter) if page_filter else "all",
                                        "a0_parity_mismatches": len(mismatches)})
            manifest["parity_mismatches"] += mismatches
            (output_dir / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"{source['document']}: A0 mismatches {len(mismatches)}, {manifest['sources'][-1]['elapsed_seconds']}s", flush=True)
            if mismatches and not allow_parity_mismatch:
                raise RuntimeError(f"STOP: A0 does not reproduce the baseline for {len(mismatches)} line(s) of "
                                   f"{source['document']}; the experiment is invalid.")
    finally:
        results.close()
        manifest["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        manifest["predictions_run"] = predictions
        (output_dir / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--documents", nargs="*", default=[], help="document name prefixes; default all")
    parser.add_argument("--configs", nargs="*", default=[c.name for c in CONFIGS])
    parser.add_argument("--pages", nargs="*", type=int, default=[], help="page numbers; needs exactly one document")
    parser.add_argument("--threads", type=int, default=4, help="ONNX Runtime threads per process (website: 4)")
    parser.add_argument("--save-crops-for", type=Path, help="text file of line keys whose crops are saved for every config")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allow-parity-mismatch", action="store_true", help="debugging only; invalidates the run")
    args = parser.parse_args(argv)
    by_name = {c.name: c for c in CONFIGS}
    if args.configs[0] != "A0" or any(name not in by_name for name in args.configs):
        raise ValueError("STOP: configs must start with A0 and be known: " + ", ".join(by_name))
    sources = select(json.loads(args.sources.read_text(encoding="utf-8"))["sources"], args.documents)
    if args.pages and len(sources) != 1:
        raise ValueError("STOP: --pages needs exactly one document")
    keys = set(args.save_crops_for.read_text(encoding="utf-8").split()) if args.save_crops_for else set()
    manifest = run(sources, args.output_dir, [by_name[n] for n in args.configs], save_all_crops_for=keys,
                   allow_parity_mismatch=args.allow_parity_mismatch, pages=set(args.pages), threads=args.threads)
    print(json.dumps({"sources": len(manifest["sources"]), "predictions_run": manifest["predictions_run"],
                      "parity_mismatches": len(manifest["parity_mismatches"])}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

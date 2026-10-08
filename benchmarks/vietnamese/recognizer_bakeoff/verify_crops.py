#!/usr/bin/env python3
"""Check that the exported crops are the images the full pipeline recognised.

Usage (PaddlePaddle environment, ``.venv``):
    python benchmarks/vietnamese/recognizer_bakeoff/verify_crops.py

Feeds the crop files to PP-OCRv6_medium_rec the way the pipeline feeds its own
crops (page by page, sorted by aspect ratio, in batches of the pipeline's
size) and compares text and score with what the pipeline returned for the same
line, recorded in the manifest as ``paddle_prediction`` and
``paddle_confidence``. If every line matches, the files in ``crops/`` are what
the pipeline handed to its recognizer, so the bake-off measures the recognizers
on the real output of the frozen detection profile.

``run_ppocr_rec.py`` recognises one crop at a time instead, which is why a few
of its predictions differ from the pipeline's: crops of one batch are padded to
a common width.
"""

from __future__ import annotations

import itertools
import sys

import bakeoff_common as bakeoff
from common import OUTPUT_ROOT, read_json
from run_ppocr_rec import MODEL_NAME, create_model

SCORE_TOLERANCE = 1e-6


def pipeline_batch_size(document: str) -> int:
    metadata = read_json(OUTPUT_ROOT / bakeoff.FROZEN_PROFILE.name / document / "metadata.json")
    pipeline = metadata["configuration"]["paddlex_pipeline_config"]
    return pipeline["SubModules"]["TextRecognition"]["batch_size"]


def main() -> int:
    import cv2

    manifest = bakeoff.load_manifest()
    model = create_model("cpu")
    matching = 0
    for (document, _), page in itertools.groupby(manifest, key=lambda row: (row["document"], row["page"])):
        rows = list(page)
        images = [
            cv2.imread(str(bakeoff.verified_crop_path(row)), cv2.IMREAD_COLOR) for row in rows
        ]
        order = sorted(range(len(rows)), key=lambda i: images[i].shape[1] / float(images[i].shape[0]))
        results = model.predict([images[i] for i in order], batch_size=pipeline_batch_size(document))
        for index, result in zip(order, results):
            matching += (
                result["rec_text"] == rows[index]["paddle_prediction"]
                and abs(result["rec_score"] - rows[index]["paddle_confidence"]) < SCORE_TOLERANCE
            )

    print(f"{MODEL_NAME}, batched like the pipeline: {matching}/{len(manifest)} lines "
          "with the pipeline's text and score")
    if matching != len(manifest):
        print("FAIL: the crops are not what the pipeline recognised")
        return 1
    print("PASS: the exported crops are the pipeline's recognition inputs")
    return 0


if __name__ == "__main__":
    sys.exit(main())

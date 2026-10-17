# Hybrid candidate H1: PDF text layer per line, B1024 fallback

**Status: ELIGIBLE_FOR_BLIND_ROUND, on non-blind evidence only.** H1 is not
integrated anywhere. The production pipeline (`demo/local_pdf_ocr/backend/`,
B1024) is unchanged. H1 runs only as an experiment on stored A0 outputs, and
it needs a blind round plus an explicit user decision before anything else
happens.

## What H1 does

For every line that B1024 (A0) detected and read, H1 does one of two things:
- if every gate passes, it uses the PDF text-layer words inside that line's
  polygon;
- otherwise it keeps the A0 text byte for byte.

A0 supplies the detection polygons, their order and the header split. No model
is run: H1 reads the text layer and renders pages with the engine's own raster
for its ink checks.

The gates run in this order (`hybrid.REASONS`); the thresholds are in
`gates.GATES`:
1. page geometry, word segmentation and hidden text layers;
2. word assignment: straddling, ambiguous, multi-line, duplicate, overlapping
   and shared words;
3. invisible, covered, clipped or superscript text;
4. untrusted font mappings: Type3, Type0 without ToUnicode, legacy Vietnamese
   encodings;
5. Unicode problems and characters outside the recognizer vocabulary;
6. ink with no word, or words with no ink;
7. token-count and gross-mismatch checks against A0.

The PDF text layer is H1's source and never a reference. Every evaluation uses
independent human labels.

## Files

| File | Role |
|---|---|
| `gates.py`, `hybrid.py` | The candidate (`h1_v1`): gates and per-line decisions. Frozen. |
| `evaluate_h1.py` | Non-blind evaluation on human labels (v1 and GT v2), checks G1 to G6. |
| `score_paired.py` | Paired A0/H1 scoring and the frozen blind verdict rule. |
| `blind.py` | Blind round: register, run-h1, select, queue, score. |
| `blind_criteria_v1.json` | Frozen sufficiency rules, gates B1 to B8 and verdicts. |
| `freeze.py` | Writes and verifies the freeze manifest. |
| `h1_freeze_manifest_v2.json` | The freeze of this branch (see below). |
| `tests/` | Unit and end-to-end tests on synthetic PDFs: no real document, no model inference. |

## Evidence so far (non-blind)

The candidate was registered on 2026-10-16, before any run on labelled
documents. It was designed on two born-digital DEV documents that have no
human labels. The document reserved for the blind round is refused by name in
the code (`hybrid.RESERVED_NAMES`).

On the 15 evaluation PDFs (1,946 lines):
- 648 lines (33.3%) came from the text layer, and 110 of those differ from A0;
- all 1,298 fallback lines are byte-identical to A0;
- line order and polygons are unchanged.

On the human-labelled lines (GT v2):

| Set | Lines | A0 CER | H1 CER | Improved | Regressed |
|---|---:|---:|---:|---:|---:|
| Pooled | 116 | 0.953% | 0.778% | 5 | 0 |
| Born-digital | 18 | 1.196% | 0.239% | 4 | 0 |
| Scanned | 98 | 0.906% | 0.882% | 1 | 0 |

The one-sided sign test gives p = 0.031. Checks G1 to G6 pass. These lines are
few and were used for earlier diagnostics, so they justify a blind round only,
not deployment.

## Freeze v2 (this branch)

`h1_freeze_manifest_v2.json` records the SHA-256 of:
- the candidate, the criteria, the evaluation tools and their tests;
- the reused quality modules, the A0 pipeline and the reference lexicons;
- the B1024 ONNX weights and metadata, and the PP-OCRv6 detector files.

It also records the gates and the library versions. Text files are hashed with
CRLF read as LF, so LF and CRLF checkouts verify alike; a line-ending-only
difference is reported as a note.

v2 replaces v1 for two reasons:
- v1 hashed raw bytes, and two reference files were CRLF in only one working
  tree;
- on this branch, the tests and tools changed: test data was sanitized and the
  hashing became CRLF-safe.

None of the following changed:
- the candidate (`gates.py`, `hybrid.py`) and its gates;
- `blind_criteria_v1.json`;
- the A0 pipeline and B1024.

H1 run from this branch reproduced all 1,946 registered decisions byte for
byte.

A clean checkout cannot verify the following, because they are not in git:
- the B1024 weights and metadata (`models/vietocr/onnx/exp_b_width1024/`);
- the detector files (`~/.paddlex/official_models/PP-OCRv6_medium_det/`);
- the library versions of the active environment;
- the pre-registration file (only its SHA-256 is recorded);
- the PDFs and A0 outputs, which `blind register` binds to each round.

Without them, `freeze verify` lists each missing file, and every blind step
refuses to run.

```bat
.venv-demo\Scripts\python.exe -m experiments.hybrid_h1.freeze verify --manifest experiments\hybrid_h1\h1_freeze_manifest_v2.json
```

## Blind round

**Prerequisites:** the user must authorize the round, and the PDFs must never
have been used for design or evaluation (`blind register` refuses them).

**Steps.** Each step calls `freeze verify` first and writes new files only. The
full commands are in the `blind.py` docstring.

1. A0 with the frozen engine (`demo.local_pdf_ocr.quality.e2e_regression --rerun-only`).
2. `blind register`.
3. `blind run-h1 --confirm-blind-round`.
4. `blind select`: every changed line, plus 30 random lines per PDF, seeded by
   the PDF hash.
5. `blind queue`. The pages show line images only: no A0, no H1, no text
   layer, no label, and no set membership.
6. A person types every line blind and exports the result.
7. `blind score`.

**Scoring rules:**
- A round is scored once.
- An attempt with problems is recorded as BLOCKED and does not use up that
  scoring.

**Sufficiency (`blind_criteria_v1.json`):**
- at least 10 PDFs, of which at least 6 are born-digital;
- at least 150 changed lines and 300 representative lines scored;
- at most 10% of lines excluded.

**Verdicts:** INSUFFICIENT_DATA, NO_GO, INCONCLUSIVE or
GO_CANDIDATE_FOR_USER_DECISION. Even the last one needs an explicit user
decision before any deployment.

## Tests

```bat
.venv-demo\Scripts\python.exe -m unittest discover -s experiments\hybrid_h1\tests -t . -p "test_*.py"
```

The end-to-end tests need the local B1024 `models/` folder (for the recognizer
vocabulary). Without it, the 3 end-to-end tests stop with "recognizer
vocabulary unavailable".

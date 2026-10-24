# Administrative document metadata

This feature reads **one existing `/api/ocr` result at a time**. It does not run
recognition, alter its output or combine text from different methods. Everything
remains local and in memory; no storage-backend integration is implemented.

## Business schema

No official storage-backend schema or full document-type catalog was found in this
repository. The following contract follows the supplied project brief: exactly
these 22 keys, **every value a JSON string**, including `numberOfPage`. Unknown
values are `""`; classification codes retain their leading zero. A later backend
integration must verify these types before sending any data.

| Key | Meaning / allowed values |
| --- | --- |
| docId | Always `""`, reserved; never generated or editable |
| arcDocCode | Full header number/notation; manually editable |
| maintenance | `01` permanent; `02` 75 years; `03` 50; `04` 30; `05` 20; `06` 10; `07` 5 |
| typeName | Only verified mappings: `01` Nghị quyết; `02` Quyết định; `22` Công văn |
| codeNumber | Before the first `/` of arcDocCode; derived, read-only |
| codeNotation | After the last `/` of arcDocCode; derived, read-only |
| issuedDate | Real calendar date in `DD-MM-YYYY`, or empty |
| organName | Unicode uppercase issuing agency from an unambiguous header |
| subject | Literal title/subject words, joining relevant lines with spaces |
| language | `01` Vietnamese; `02` English; ambiguous/bilingual text stays empty |
| numberOfPage | Source reader's PDF count (1–6), or `"1"` for a source image |
| inforSign | Manual only |
| keyword | Manual only; no generated keywords |
| mode | `01` public; `02` conditional; `03` secret; initially empty |
| confidenceLevel | `01` if isCan is `"0"`; **all other values, including empty, yield `02`** |
| autograph | Manual only |
| format | `01` good; `02` normal; `03` damaged; manual only |
| process | `0` no; `1` yes; manual only |
| riskRecovery | `0` no; `1` yes; manual only |
| riskRecoveryStatus | `01` backed up; `02` not backed up; manual only |
| description | Manual notes; never generated from OCR |
| isCan | `0` red seal; `1` other color; empty if unknown; manual visual confirmation |

`confidenceLevel` is a **business classification, not OCR probability**. The
initial `02` is explicitly marked for review because the seal is unknown.
`mode` is never inferred from document content and never silently assigned `01`.
The UI warns that a future storage backend may treat an empty mode as public,
and requires confirmation before exporting or copying an unclassified draft.
The exported JSON itself retains `mode: ""`.

## Conservative extraction and provenance

- Page 1 header only for document identity, agency, issuance date and type. Body
  markers and the first title/subject bound the identity area. Citations on later
  pages, body references and dates/file names are not used as current identity.
- Explicit `Số:` labels support wrapped lines and whitespace around `/`. Unicode
  dashes are preserved as extracted, including PDF font mappings to U+2010.
  Ambiguous OCR characters such as `O` in the number or `?` are never repaired;
  these candidates require review. Competing identifiers/dates stay unresolved.
- Issuance dates need an explicit administrative `ngày … tháng … năm …` header
  pattern and pass a UTC calendar check. No missing day/month is invented.
- National titles and mottos are excluded from issuing agencies. Multiple agency
  candidates/cascaded authorities are left for manual resolution.
- An explicit document-type heading is required. `V/v` alone does not imply
  Công văn. The other 29 codes are neither invented nor offered in the dropdown.
- `V/v`, `Về việc` and main title continuations are bounded by column, paragraph
  gap, header/body markers and length. Complex layouts may remain empty or need
  review. No spelling, diacritic or legal-name correction is applied.
- Native bbox coordinates describe **blocks in PDF points**. OCR polygons describe
  lines in **raster pixels**. Analysis normalizes them within their own page only.
  Evidence retains page/line/literal source text and coordinate provenance; the UI
  shows quotations and never invents a precise highlight from a coarse block box.

Status and evidence live in a separate draft, never in business JSON. Counts of
recognized/confirmed fields describe coverage, not accuracy. Manual edits and
confirmations are scoped by method, survive tab changes, and do not change raw
TXT/JSON. New files, reruns and restoration confirm loss of dirty edits. A failed
rerun restores the previous raw result and preserves its metadata draft.

All populated text fields extracted from `vietocr_ocr` require visual review,
including their derived number/notation. The model has no calibrated confidence
for this task. A literal OCR quote is provenance, not proof that every character
matches the paper. No rule repairs OCR spelling using the synthetic labels.

The export filename is `<name>_<method>_metadata.json`, separate from the original
`<name>_<method>.json`. Invalid dates/codes block metadata export. Missing/review
fields require a draft-export confirmation; they are not filled to make the form
look complete. The reserved empty docId is excluded from the missing-field count.

## Synthetic example (officialLetter)

This example is authored test content, not a real administrative record. The JSON
fixture uses ASCII hyphens; PDFs may expose a different literal Unicode dash due
to their font's ToUnicode mapping, which extraction preserves.

```json
{
  "docId": "",
  "arcDocCode": "00103/TEST-CN",
  "maintenance": "",
  "typeName": "22",
  "codeNumber": "00103",
  "codeNotation": "TEST-CN",
  "issuedDate": "08-10-2026",
  "organName": "VĂN PHÒNG KIỂM THỬ",
  "subject": "kiểm thử trích xuất thông tin trên tài liệu tổng hợp, giữ nguyên tiếng Việt",
  "language": "01",
  "numberOfPage": "1",
  "inforSign": "",
  "keyword": "",
  "mode": "",
  "confidenceLevel": "02",
  "autograph": "",
  "format": "",
  "process": "",
  "riskRecovery": "",
  "riskRecoveryStatus": "",
  "description": "",
  "isCan": ""
}
```

Decision and resolution fixtures use respectively `00002/QĐ-TEST` / type `02` and
`00321/NQ-TEST` / type `01`; other values follow the same explicit synthetic source.
Generate all **10** JSON input/example pairs, then optional PDFs, outside Git:

```sh
node demo/local_pdf_ocr/frontend/scripts/export_metadata_fixtures.mjs <outside-repo-folder>
python desktop/scripts/make_metadata_fixtures.py <outside-repo-folder> --font <installed-Unicode-TTF>
```

The fixtures cover an official letter, decision, resolution, two-column header,
ambiguous code, competing dates, missing code, unreadable scan, body references and
a wrapped number. No PDFs, font files, model files or research labels are committed.

## Verification

```sh
cd demo/local_pdf_ocr/frontend
npm ci
npm test
npm run build
```

Use current Node 22 or later for the test dependencies. The pure extraction tests
and React interaction tests run in both model-free CI workflows. The existing
Electron smoke additionally checks the default metadata tab, exact 22-string-key
export, access warning, real JSON clipboard, manual-edit persistence and confirmed
restoration, while retaining the original preview, TXT/raw JSON, copy, security,
model-refusal, crash/restart and shutdown checks. Run its normal checker as described
in `desktop/README.md`; use synthetic inputs and evidence folders outside Git.

Model-free tests do not measure recognition accuracy. Real B1024 regression must
use verified local models and permitted DEV/synthetic inputs. Compare raw TXT bytes
and JSON recognition/geometry fields; independent requests have different timing
fields. No private/blind labels may be used for tuning or scoring these rules.
No accuracy claim on independent real administrative documents is made here.

For the three hand-labeled synthetic PDF fixtures, the local frozen B1024 run
produced 27 correct populated values, 3 populated differences, 36 empty values and
no missing expected populated field (66 field slots). Each difference was the
same OCR word `thử` → `thứ` in the subject; extraction preserved it unchanged.
There are 27 review flags across these drafts (overlapping the value counts),
including the unconfirmed seal-based business code. These three fixtures are
development examples, not an independent accuracy benchmark. Reproduce the
score from their real OCR exports with:

```sh
node demo/local_pdf_ocr/frontend/scripts/score_synthetic_metadata.mjs <external-labeled-smoke-folder>
```

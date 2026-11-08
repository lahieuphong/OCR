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
| typeName | Only verified mappings: `01` Nghị quyết; `02` Quyết định; `22` Công văn (also from the letter layout, for review) |
| codeNumber | Before the first `/` of arcDocCode; derived, read-only |
| codeNotation | After the last `/` of arcDocCode; derived, read-only |
| issuedDate | Real calendar date in `DD-MM-YYYY`, or empty |
| organName | Unicode uppercase issuing agency from an unambiguous header |
| subject | Literal title/subject words, joining relevant lines with spaces; a leading `V/v` or `Về việc` is kept as printed (the owner's records keep both) |
| language | `01` Vietnamese; `02` English; ambiguous/bilingual text stays empty |
| numberOfPage | Source reader's PDF count (1–6; up to 1000 in `metadata_fast`, which reads only page 1), or `"1"` for a source image |
| inforSign | The short mark written in the top-right corner of page 1, above the national motto (e.g. the receiving portal's `TTĐT`, `TTĐT(2)`): as read, inner spaces removed, always for review; otherwise manual |
| keyword | Manual only; no generated keywords |
| mode | `01` public; `02` conditional; `03` secret. `01` only from the publication source (below), for review; otherwise empty and marked for verification |
| confidenceLevel | `01` if isCan is `"0"`; **all other values, including empty, yield `02`** |
| autograph | Manual only |
| format | `01` good; `02` normal; `03` damaged; manual only |
| process | `0` no; `1` yes; manual only |
| riskRecovery | `0` no; `1` yes; manual only |
| riskRecoveryStatus | `01` backed up; `02` not backed up; manual only |
| description | Manual notes; never generated from OCR |
| isCan | `0` when the backend's seal check finds a round red seal; `1` other color (manual only); empty if unknown |

`confidenceLevel` is a **business classification, not OCR probability**. It is
`01` when a red seal was found; otherwise the initial `02` is marked for review
because the seal is unknown.

The seal check (`backend/seal_colour.py`, every mode) looks at page pixels, not
text: pages render at 100 dpi from the last page back (20 pages, then the first
20 of a longer PDF), and the first red, round (convex hull ≈ π/4 of its box),
22–60 mm mark is the seal. Rectangular stamps and the small e-signature emblem
do not qualify. A scan whose page image is greyscale is reported as black and
white: its seal colour cannot be known and stays empty. The result's `seal` key
names the page and size, which the metadata panel shows as evidence.
`mode` is never inferred from OCR content. The one source used is publication:
the Government e-portal signs the documents it publishes, and a PDF whose page-1
signature block names `thongtinchinhphu@chinhphu.vn` gets `01`, always for review,
with a note that this is a classification from the publication source, not an OCR
result or an internal access decision (the certificate itself is not checked). A
secrecy mark (`MẬT`, `TỐI MẬT`, `TUYỆT MẬT`) on page 1 blocks it. Otherwise `mode`
stays empty and is marked for verification. The UI warns that a future storage
backend may treat an empty mode as public, and requires confirmation before
exporting or copying an unclassified draft; the exported JSON retains `mode: ""`.

## Conservative extraction and provenance

- Page 1 header only for document identity, agency, issuance date and type. Body
  markers and the first title/subject bound the identity area. Citations on later
  pages, body references and dates/file names are not used as current identity.
- Explicit `Số:` labels support wrapped lines and whitespace around `/`. Unicode
  dashes are preserved as extracted, including PDF font mappings to U+2010.
  Ambiguous OCR characters such as `O` in the number or `?` are never repaired;
  these candidates require review. Competing identifiers/dates stay unresolved.
  A bare `Số:` takes its value from the next line or from the same row on its
  right. A misread label with its colon (`3ố:`, `Ố:`) still marks the number, and
  digits read with spaces before the first `/` (`2 1/2026/…`) are joined; both
  keep every character as read and require review.
- Issuance dates need an explicit administrative `ngày … tháng … năm …` header
  pattern and pass a UTC calendar check. No missing day/month is invented. A day
  or month read as two digits with a space (`ngày 0 7 tháng`) is joined, for review.
- National titles and mottos are excluded from issuing agencies. Multiple agency
  candidates/cascaded authorities are left for manual resolution. When the detector
  merges both header columns into one line, the agency is the text before
  `CỘNG HÒA`. The signing portal's `Cơ quan phát hành:` mark is signature text.
- An explicit document-type heading is required. `V/v` alone does not imply
  Công văn, except in the official-letter layout: a `V/v` line in the left column
  right under `Số:` and no title gives `22`, for review. `THÔNG TƯ` is a title
  without a code. The other codes are neither invented nor offered in the dropdown.
- `V/v`, `Về việc` and main title continuations are bounded by column, paragraph
  gap (absolute, and a step 1.7 times the subject's own line spacing), header/body
  markers, upper-case agency lines and length. Ruling lines and underscores are not
  text. Complex layouts may remain empty or need review. No spelling, diacritic or
  legal-name correction is applied.
- An arrival stamp's field (`Ngày:`, `Giờ:`, `Số đến:`) beside its `ĐẾN` mark is the
  stamp when its value is a date or noise without any word (no two letters in a
  row, such as handwriting read as `0g/9/2026`). A wide line that starts with such
  a field and goes on with words (`Ngày: 03.14./2024, Sửa đổi, bổ sung…`) is split
  after the field's value; both parts get boxes estimated from character counts.
  A subject that only touches the stamp is filled for review, with a note. A stamp
  field holding words cannot be separated: it is mixed with the subject, which
  then stays empty for review with its candidate shown.
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
  "subject": "V/v kiểm thử trích xuất thông tin trên tài liệu tổng hợp, giữ nguyên tiếng Việt",
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

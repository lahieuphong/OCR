// Score ONLY these authored synthetic fixtures. No PDF text layer is read as OCR ground truth.
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {SYNTHETIC_GOLD} from "../src/test/fixtures/metadataGold.js";
import {createDocumentDraft, documentValues, FIELD_KEYS} from "../src/lib/documentFields.js";

const folder = path.resolve(process.argv[2] || "");
if (!process.argv[2]) throw Error("Specify the external synthetic smoke evidence folder");
const root = fileURLToPath(new URL("../../../..", import.meta.url));
const relative = path.relative(root, folder);
if (relative === "" || (!relative.startsWith(".." + path.sep) && !path.isAbsolute(relative))) throw Error("Scoring evidence must stay outside the repository.");
const totals = {correctPopulated:0, wrongPopulated:0, empty:0, missingExpected:0, needsReview:0};
const documents = [];
for (const [name, gold] of Object.entries(SYNTHETIC_GOLD)) {
  const raw = JSON.parse(fs.readFileSync(path.join(folder, name, "downloads", name + "_vietocr_ocr.json"), "utf8"));
  const draft = createDocumentDraft(raw), values = documentValues(draft);
  const counts = {correctPopulated:0, wrongPopulated:0, empty:0, missingExpected:0, needsReview:0};
  const differences = [];
  for (const key of FIELD_KEYS) {
    if (!values[key]) {counts.empty++; if (gold[key]) counts.missingExpected++;}
    else if (values[key] === gold[key]) counts.correctPopulated++;
    else {counts.wrongPopulated++; differences.push({field:key,expected:gold[key],actual:values[key]});}
    if (draft.fields[key].status === "review") counts.needsReview++;
  }
  for (const key of Object.keys(totals)) totals[key] += counts[key];
  documents.push({name,counts,differences});
}
const report = {scope:"Three authored synthetic PDFs processed by real frozen B1024; not an independent real-document accuracy study.",
  noPdfTextLayerGroundTruth:true, totals, documents};
fs.writeFileSync(path.join(folder,"synthetic-metadata-score.json"), JSON.stringify(report,null,2));
console.log(JSON.stringify(report,null,2));

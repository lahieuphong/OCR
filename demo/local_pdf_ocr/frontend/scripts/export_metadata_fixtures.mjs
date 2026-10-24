// Writes synthetic inputs and business JSON examples OUTSIDE the checkout.
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {SYNTHETIC_CASES} from "../src/test/fixtures/administrativeDocuments.js";
import {createDocumentDraft, serializeDocumentFields} from "../src/lib/documentFields.js";

const root = fileURLToPath(new URL("../../../..", import.meta.url));
const output = path.resolve(process.argv[2] || "");
const relative = path.relative(root, output);
if (!process.argv[2] || relative === "" || (!relative.startsWith(".." + path.sep) && !path.isAbsolute(relative))) throw Error("Choose an output folder outside the repository.");
fs.mkdirSync(output, {recursive:true});
for (const [name, raw] of Object.entries(SYNTHETIC_CASES)) {
  fs.writeFileSync(path.join(output, name + ".source.json"), JSON.stringify(raw, null, 2));
  fs.writeFileSync(path.join(output, name + ".metadata.json"), serializeDocumentFields(createDocumentDraft(raw)));
}
console.log(`Wrote ${Object.keys(SYNTHETIC_CASES).length} synthetic JSON fixture pairs outside Git.`);

/** Replay FIRST-PAGE number-prefix failure against pre-existing local OCR JSON.
 *
 * This is a MODEL-FREE SYNTHETIC perturbation of real geometry, NOT
 * observed OCR failure. It does not use labels, filenames as ground truth,
 * rerun PDF OCR, touch weights or rewrite source/outputs.
 *
 *   node scripts/replayNumberPrefix.mjs --dir E:\path\to\private_json
 *   node scripts/replayNumberPrefix.mjs --file E:\some.json --output E:\report.json
 */
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import {pathToFileURL} from "node:url";
import {findNumberReviewCandidates} from "../src/numberReview.js";

const PREFIX=/^\s*s[ốo]\s*:/iu;
const DATE=/\bngày\s*\d{1,2}\s+tháng\s*\d{1,2}/iu;
const copy=value=>structuredClone(value);
const summarize=entries=>({
  warnings:entries.map(x=>({line_index:x.line_index,reasons:x.reasons})),
  crop_candidates:entries.filter(x=>x.polygon!==null).length,
  page_level_manual_check:entries.some(x=>x.reasons.includes("number_field_not_located")),
});

export function replayDocument(doc) {
  if(doc?.method!=="vietocr_ocr"||doc?.used_ocr!==true||!Array.isArray(doc.pages)){
    throw Error("Not a VietOCR rendered-page JSON report");
  }
  const page=doc.pages.find(p=>p.page===1);
  if(!page||!Array.isArray(page.lines))throw Error("Missing page 1 lines");
  const header=page.lines.filter(x=>
    typeof x.text==="string"&&PREFIX.test(x.text)&&
    Array.isArray(x.polygon)&&x.polygon.length===4);
  // No hint from filename or human reference. Ambiguous inputs fail closed.
  if(header.length!==1)throw Error("Expected exactly one original first-page Số: header; found "+header.length);
  const original=header[0];
  const originalIndex=original.line_index;
  const base=JSON.stringify(doc);
  function mutate(action){
    const sample=copy(doc);
    const p=sample.pages.find(x=>x.page===1);
    const line=p.lines.find(x=>x.line_index===originalIndex);
    if(!line)throw Error("Source line ID changed");
    if(action==="corrupt_prefix"){
      line.text=line.text.replace(PREFIX,"5ô:");
    } else if(action==="delete_prefix"){
      line.text=line.text.replace(PREFIX,"");
    } else if(action==="miss_detection"){
      p.lines=p.lines.filter(x=>x.line_index!==originalIndex);
    } else if(action==="lose_dateline"){
      line.text=line.text.replace(PREFIX,"5ô:");
      p.lines=p.lines.filter(x=>!(DATE.test(x.text||"")&&
        Array.isArray(x.polygon)&&Math.min(...x.polygon.map(pt=>pt[1]))<.38*p.height));
    } else {throw Error("Invalid replay action");}
    const candidates=findNumberReviewCandidates(sample);
    if(candidates.some(c=>c.reasons.includes("non_digit_serial")&&action==="corrupt_prefix")){
      throw Error("Simulation unexpectedly retained an OCR prefix");
    }
    return {
      ...summarize(candidates),
      target_line_located:candidates.some(x=>x.line_index===originalIndex),
    };
  }
  const result={
    line_index:originalIndex,
    observed_original:summarize(findNumberReviewCandidates(doc)),
    simulations:{
      corrupt_prefix:mutate("corrupt_prefix"),
      delete_prefix:mutate("delete_prefix"),
      miss_detection:mutate("miss_detection"),
      lose_dateline:mutate("lose_dateline"),
    },
  };
  if(JSON.stringify(doc)!==base)throw Error("STOP: attempted source mutation");
  return result;
}

export function replayPaths(paths){
  if(!Array.isArray(paths)||paths.length===0)throw Error("No OCR JSON files");
  const seenHashes=new Set();
  const rows=[];
  for(const filename of [...paths].sort()){
    const raw=fs.readFileSync(filename);
    const sha=crypto.createHash("sha256").update(raw).digest("hex");
    if(seenHashes.has(sha))throw Error("STOP: duplicate OCR JSON bytes in replay");
    seenHashes.add(sha);
    const record=JSON.parse(raw.toString("utf8"));
    const outcome=replayDocument(record);
    if(sha!==crypto.createHash("sha256").update(fs.readFileSync(filename)).digest("hex")){
      throw Error("STOP: OCR source changed during replay");
    }
    rows.push({file:path.basename(filename),source_json_sha256:sha,...outcome});
  }
  const total=rows.length;
  const corruptLocated=rows.filter(r=>r.simulations.corrupt_prefix.target_line_located).length;
  const corruptManual=rows.filter(r=>r.simulations.corrupt_prefix.page_level_manual_check).length;
  const extraCrops=rows.filter(r=>r.simulations.corrupt_prefix.crop_candidates!==1&&!r.simulations.corrupt_prefix.page_level_manual_check).length;
  return {
    status:"SIMULATED_PREFIX_FAILURE_REPLAY_NOT_REAL_OCR",
    source:"original user-local OCR JSON; only in-memory synthetic failure",
    input_documents:total,
    observed_original_alerts:rows.reduce((n,r)=>n+r.observed_original.warnings.length,0),
    corrupt_prefix_exact_crop_documents:corruptLocated,
    corrupt_prefix_page_level_review_documents:corruptManual,
    corrupt_prefix_ambiguous_candidate_documents:extraCrops,
    all_synthetic_corruptions_surface_a_review:corruptLocated+corruptManual===total&&extraCrops===0,
    pdf_or_model_reprocessed:false,
    reference_labels_used:false,
    source_json_rewritten:false,
    automatic_ocr_correction:false,
    deployment_approved:false,
    merge_approved:false,
    limitations:[
      "Artificially edits the already recognized Số: prefix; NOT evidence of live detector/recognizer recall.",
      "When a dateline is absent or a number box is missing, only page-level human review can be requested.",
      "No text/reference accuracy metrics; real-world PDF coverage and false positives remain unmeasured.",
    ],
    rows,
  };
}

function parseArgs(argv){
  const files=[],dirs=[];
  let out=null;
  for(let i=0;i<argv.length;i++){
    if(argv[i]==="--file"&&argv[i+1])files.push(argv[++i]);
    else if(argv[i]==="--dir"&&argv[i+1])dirs.push(argv[++i]);
    else if(argv[i]==="--output"&&argv[i+1])out=argv[++i];
    else throw Error("Invalid args: use --dir, --file or --output");
  }
  for(const folder of dirs){
    for(const entry of fs.readdirSync(folder)){
      if(entry.endsWith("_vietocr_ocr_header_split.json")){
        files.push(path.join(folder,entry));
      }
    }
  }
  const unique=[...new Set(files.map(f=>path.resolve(f)))];
  return {files:unique,out};
}

if(process.argv[1]&&import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href){
  try{
    const {files,out}=parseArgs(process.argv.slice(2));
    const report=replayPaths(files);
    if(out){
      if(fs.existsSync(out))throw Error("STOP: refusing to overwrite existing report");
      if(!fs.existsSync(path.dirname(out)))throw Error("Output directory missing");
      fs.writeFileSync(out,JSON.stringify(report,null,2),"utf8");
    }
    console.log(JSON.stringify({
      status:report.status,
      input_documents:report.input_documents,
      corrupt_prefix_exact_crop_documents:report.corrupt_prefix_exact_crop_documents,
      corrupt_prefix_page_level_review_documents:report.corrupt_prefix_page_level_review_documents,
      corrupt_prefix_ambiguous_candidate_documents:report.corrupt_prefix_ambiguous_candidate_documents,
      all_synthetic_corruptions_surface_a_review:report.all_synthetic_corruptions_surface_a_review,
      output:out||"stdout-only summary (provide --output for detailed report)",
    },null,2));
  }catch(error){
    console.error("STOP:",error.message);process.exitCode=1;
  }
}

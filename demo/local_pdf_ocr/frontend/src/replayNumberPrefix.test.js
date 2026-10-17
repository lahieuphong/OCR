import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {replayDocument,replayPaths} from "../scripts/replayNumberPrefix.mjs";

const L=(line_index,text,x,y,w=240)=>({
  line_index,text,
  polygon:[[x,y],[x+w,y],[x+w,y+30],[x,y+30]],
});
function sample({withDate=true,extraTitle=false}={}){
  return {
    method:"vietocr_ocr",used_ocr:true,
    text:"Original text remains untouched",pages:[{
      page:1,width:1191,height:1685,
      lines:[
        L(5,"BỘ XÂY DỰNG",210,120),
        L(8,"Số: 10427/VPCP-KGVX",213,232,267),
        ...(withDate?[L(9,"Hà Nội, ngày 15 tháng 9 năm 2025",636,233,431)]:[]),
        ...(extraTitle?[L(10,"V/v triển khai nhiệm vụ mẫu",222,248,350)]:[]),
        L(21,"Căn cứ số 4H7/QĐ-TTg",177,800,450),
      ],
    }],
  };
}
test("replay finds exact number crop despite a V/v same-row collision",()=>{
  const doc=sample({extraTitle:true});
  const old=JSON.stringify(doc);
  const replay=replayDocument(doc);
  assert.equal(replay.simulations.corrupt_prefix.crop_candidates,1);
  assert.equal(replay.simulations.corrupt_prefix.target_line_located,true);
  assert.equal(replay.simulations.delete_prefix.crop_candidates,1);
  assert.equal(replay.simulations.miss_detection.crop_candidates,0);
  assert.equal(replay.simulations.miss_detection.page_level_manual_check,true);
  assert.equal(replay.simulations.lose_dateline.page_level_manual_check,true);
  assert.equal(JSON.stringify(doc),old);
});
test("without recognizable issue date, no invented number crop; review entire first page",()=>{
  const replay=replayDocument(sample({withDate:false}));
  assert.equal(replay.simulations.corrupt_prefix.target_line_located,false);
  assert.equal(replay.simulations.corrupt_prefix.page_level_manual_check,true);
});
test("source wrong mode or ambiguous header must stop without using filename",()=>{
  const doc=sample();
  assert.throws(()=>replayDocument({...doc,method:"native_text"}),/Not a VietOCR/);
  doc.pages[0].lines.push(L(11,"Số: 218/TB-VPCP",180,320));
  assert.throws(()=>replayDocument(doc),/exactly one original/);
});
test("file SHA provenance and source bytes remain unchanged in offline replay",()=>{
  const folder=fs.mkdtempSync(path.join(os.tmpdir(),"prefix-replay-"));
  try{
    const file=path.join(folder,"synthetic.json");
    fs.writeFileSync(file,JSON.stringify(sample()),"utf8");
    const original=fs.readFileSync(file);
    const report=replayPaths([file]);
    assert.equal(report.input_documents,1);
    assert.equal(report.corrupt_prefix_exact_crop_documents,1);
    assert.equal(report.corrupt_prefix_page_level_review_documents,0);
    assert.equal(report.all_synthetic_corruptions_surface_a_review,true);
    assert.equal(report.pdf_or_model_reprocessed,false);
    assert.equal(report.reference_labels_used,false);
    assert.equal(report.source_json_rewritten,false);
    assert.equal(report.automatic_ocr_correction,false);
    assert.deepEqual(fs.readFileSync(file),original);
    assert.throws(()=>replayPaths([file,file]),/duplicate OCR JSON bytes/);
  }finally{fs.rmSync(folder,{recursive:true,force:true});}
});

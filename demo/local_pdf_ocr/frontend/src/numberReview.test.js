import test from "node:test";
import assert from "node:assert/strict";
import {findNumberReviewCandidates} from "./numberReview.js";

const W=1192,H=1686;
const line=(line_index,text,x,y,w=270,h=31)=>({
  line_index,text,polygon:[[x,y],[x+w,y],[x+w,y+h],[x,y+h]],
});
function doc(numberText,custom=[]){
  return {
    method:"vietocr_ocr",used_ocr:true,
    text:"Do not modify original output",
    pages:[{page:1,width:W,height:H,lines:[
      line(5,"BỘ XÂY DỰNG",210,130),
      line(8,numberText,210,233),
      line(9,"Hà Nội, ngày 12 tháng 3 năm 2025",650,235,400),
      line(22,"số điều của Luật Mẫu được sửa đổi",185,780,700),
      ...custom,
    ]}],
  };
}
test("detects non-digit serial in number header not reference metadata",()=>{
  const data=doc("Số: 4H7 /QĐ-UBQGHT2030");
  const old=JSON.stringify(data);
  const out=findNumberReviewCandidates(data);
  assert.equal(out.length,1);
  assert.deepEqual(out[0].reasons,["non_digit_serial"]);
  assert.equal(JSON.stringify(data),old);
});
test("space inside digits is suspicious but space before slash is not",()=>{
  assert.deepEqual(findNumberReviewCandidates(doc("Số: 3 7/2025/TT-BCT"))[0].reasons,["split_digits"]);
  assert.deepEqual(findNumberReviewCandidates(doc("Số: RU8/TB-VPCP"))[0].reasons,["non_digit_serial"]);
  assert.deepEqual(findNumberReviewCandidates(doc("Số: 59 /2025/TT-BXD")),[]);
  for(const text of ["Số: 147/QĐ","Số: 10427/VPCP-KGVX","Số: 336/NQ-CP",
                     "Số: 57/2025/QĐ-TTg"]){
    assert.deepEqual(findNumberReviewCandidates(doc(text)),[]);
  }
});
test("geometry catches number box when prefix is corrupted or absent",()=>{
  const out=findNumberReviewCandidates(doc("5ô: 4H7 /QĐ-HT"));
  assert.equal(out.length,1);
  assert.deepEqual(out[0].reasons,["geometry_possible_number"]);
  assert.equal(out[0].line_index,8);
  assert.equal(out[0].text,"5ô: 4H7 /QĐ-HT");
});
test("if no prefix AND no dateline geometry, warn rather than claim clean",()=>{
  const data=doc("Văn bản số 4H7");
  data.pages[0].lines=data.pages[0].lines.filter(l=>!l.text.startsWith("Hà Nội"));
  const out=findNumberReviewCandidates(data);
  assert.equal(out.length,1);
  assert.deepEqual(out[0].reasons,["number_field_not_located"]);
  assert.equal(out[0].polygon,null);
});
test("native text mode or no result must not have OCR flags",()=>{
  assert.deepEqual(findNumberReviewCandidates(null),[]);
  assert.deepEqual(findNumberReviewCandidates({...doc("Số: 4H7"),used_ocr:false}),[]);
  assert.deepEqual(findNumberReviewCandidates({...doc("Số: 4H7"),method:"native_text"}),[]);
});
test("title and body references never cause false alarms",()=>{
  const data=doc("Số: 815/QĐ-TTg",[
    line(20,"Số: RU8/TB-VPCP",220,900),
    line(21,"Căn cứ số 4H7/QĐ",220,950),
  ]);
  assert.deepEqual(findNumberReviewCandidates(data),[]);
});

test("missing prefix: neighboring agency name without serial shape is NOT auto-cropped",()=>{
  const data=doc("BỘ XÂY DỰNG");
  const found=findNumberReviewCandidates(data);
  assert.equal(found.length,1);
  assert.equal(found[0].line_index,null);
  assert.deepEqual(found[0].reasons,["number_field_not_located"]);
});

test("missing source number detection box: show page-level review not a fake polygon",()=>{
  const data=doc("Số: 815/QĐ-TTg");
  data.pages[0].lines=data.pages[0].lines.filter(l=>l.line_index!==8);
  const found=findNumberReviewCandidates(data);
  assert.equal(found.length,1);
  assert.equal(found[0].polygon,null);
  assert.equal(found[0].review_key,"p1_unlocated");
});

test("missing prefix + no dateline for a split-digit header: no invented coordinates",()=>{
  const data=doc("Sô: 3 7/2025/TT-BCT");
  data.pages[0].lines=data.pages[0].lines.filter(l=>l.line_index!==9);
  const found=findNumberReviewCandidates(data);
  assert.deepEqual(found.map(x=>x.reasons),[["number_field_not_located"]]);
  assert.equal(found[0].polygon,null);
});

test("malformed geometry never leads to an unsafe crop",()=>{
  const data=doc("Số: RU8");
  const number=data.pages[0].lines.find(l=>l.line_index===8);
  number.polygon=[[NaN,3],[230,3],[230,40],[NaN,40]];
  const found=findNumberReviewCandidates(data);
  assert.deepEqual(found.map(x=>x.reasons),[["number_field_not_located"]]);
});

test("unrelated legitimate title on date row stays out of number alert",()=>{
  const data=doc("THÔNG TƯ VỀ CHI PHÍ");
  const found=findNumberReviewCandidates(data);
  assert.equal(found.length,1);
  assert.equal(found[0].review_key,"p1_unlocated");
});

test("prefix recognized as valid prevents geometry false alarms elsewhere",()=>{
  const data=doc("Số: 59 /2025/TT-BXD",[
    line(12,"4H7 /QĐ-UNRELATED",200,236,250,30),
  ]);
  assert.deepEqual(findNumberReviewCandidates(data),[]);
});

test("all outcomes are hints only: copies remain byte-for-byte equal in JSON",()=>{
  for(const sample of [
    doc("Số: RU8/TB-VPCP"),doc("Số: 59 /2025/TT-BXD"),
    doc("5ô: 4H7 /QĐ-HT"),doc("BỘ XÂY DỰNG"),
  ]){
    const before=JSON.stringify(sample);
    const out=findNumberReviewCandidates(sample);
    assert.equal(JSON.stringify(sample),before);
    assert.ok(out.every(x=>Array.isArray(x.reasons)&&x.reasons.length));
    assert.ok(out.every(x=>!Object.hasOwn(x,"replacement_text")));
  }
});

test("real-layout sample: V/v line beside date is not a second number candidate",()=>{
  const data={
    method:"vietocr_ocr",used_ocr:true,
    pages:[{page:1,width:1191,height:1685,lines:[
      line(8,"5ô: 10427/VPCP-KGVX",213,232,267,28),
      line(9,"Hà Nội, ngày 15 tháng 9 năm 2025",636,233,431,30),
      line(10,"V/v triển khai nhiệm vụ mẫu",222,248,350,30),
    ]}],
  };
  const original=JSON.stringify(data);
  const found=findNumberReviewCandidates(data);
  assert.deepEqual(found.map(x=>x.line_index),[8]);
  assert.equal(found[0].reasons[0],"geometry_possible_number");
  assert.equal(JSON.stringify(data),original);
});

test("date-adjacent V/v with a year after slash is not a serial number",()=>{
  const data=doc("V/v 2026 triển khai",[]);
  assert.deepEqual(findNumberReviewCandidates(data).map(x=>x.reasons),
                   [["number_field_not_located"]]);
});

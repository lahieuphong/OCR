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
      line(9,"Hà Nội, ngày 06 tháng 10 năm 2026",650,235,400),
      line(22,"số điều của Luật Giá được sửa đổi",185,780,700),
      ...custom,
    ]}],
  };
}
test("detects non-digit serial in number header not reference metadata",()=>{
  const data=doc("Số: 1H9 /QĐ-UBQGAPEC2027");
  const old=JSON.stringify(data);
  const out=findNumberReviewCandidates(data);
  assert.equal(out.length,1);
  assert.deepEqual(out[0].reasons,["non_digit_serial"]);
  assert.equal(JSON.stringify(data),old);
});
test("space inside digits is suspicious but space before slash is not",()=>{
  assert.deepEqual(findNumberReviewCandidates(doc("Số: 2 1/2026/TT-BCT"))[0].reasons,["split_digits"]);
  assert.deepEqual(findNumberReviewCandidates(doc("Số: RU6/TB-VPCP"))[0].reasons,["non_digit_serial"]);
  assert.deepEqual(findNumberReviewCandidates(doc("Số: 76 /2026/TT-BXD")),[]);
  for(const text of ["Số: 149/QĐ","Số: 10314/VPCP-KGVX","Số: 324/NQ-CP",
                     "Số: 48/2026/QĐ-TTg"]){
    assert.deepEqual(findNumberReviewCandidates(doc(text)),[]);
  }
});
test("geometry catches number box when prefix is corrupted or absent",()=>{
  const out=findNumberReviewCandidates(doc("5ô: 1H9 /QĐ-APEC"));
  assert.equal(out.length,1);
  assert.deepEqual(out[0].reasons,["geometry_possible_number"]);
  assert.equal(out[0].line_index,8);
  assert.equal(out[0].text,"5ô: 1H9 /QĐ-APEC");
});
test("if no prefix AND no dateline geometry, warn rather than claim clean",()=>{
  const data=doc("Văn bản số 1H9");
  data.pages[0].lines=data.pages[0].lines.filter(l=>!l.text.startsWith("Hà Nội"));
  const out=findNumberReviewCandidates(data);
  assert.equal(out.length,1);
  assert.deepEqual(out[0].reasons,["number_field_not_located"]);
  assert.equal(out[0].polygon,null);
});
test("native text mode or no result must not have OCR flags",()=>{
  assert.deepEqual(findNumberReviewCandidates(null),[]);
  assert.deepEqual(findNumberReviewCandidates({...doc("Số: 1H9"),used_ocr:false}),[]);
  assert.deepEqual(findNumberReviewCandidates({...doc("Số: 1H9"),method:"native_text"}),[]);
});
test("title and body references never cause false alarms",()=>{
  const data=doc("Số: 738/QĐ-TTg",[
    line(20,"Số: RU6/TB-VPCP",220,900),
    line(21,"Căn cứ số 1H9/QĐ",220,950),
  ]);
  assert.deepEqual(findNumberReviewCandidates(data),[]);
});

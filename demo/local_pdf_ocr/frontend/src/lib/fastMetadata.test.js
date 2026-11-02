import {describe, expect, test} from "vitest";
import {createDocumentDraft, documentValues, FIELD_KEYS} from "./documentFields.js";
import {fastMetadataDocument, DECREE_SUBJECT} from "../test/fixtures/fastMetadata.js";

describe("fast header metadata source evidence", () => {
  test.each([false,true])("decree header keeps source pages and ignores e-signature evidence (native=%s)", native => {
    const raw=fastMetadataDocument({native,stamp:true}), snapshot=JSON.stringify(raw);
    const draft=createDocumentDraft(raw), values=documentValues(draft);
    expect(Object.keys(values)).toEqual(FIELD_KEYS);
    expect(values).toMatchObject({docId:"",arcDocCode:"00042/2025/NĐ-QA",codeNumber:"00042",codeNotation:"NĐ-QA",
      issuedDate:"14-02-2025",organName:"ỦY BAN NHÂN DÂN TỈNH KIỂM THỬ",subject:DECREE_SUBJECT,language:"01",numberOfPage:"6",typeName:""});
    expect(draft.fields.typeName.status).toBe("review");
    expect(draft.typeLabel).toBe("Nghị định");
    expect(draft.fields.subject.evidence.map(item=>item.text).join(" ")).not.toContain("Căn cứ");
    expect(draft.fields.organName.evidence.every(item=>!item.text.includes("Ký bởi"))).toBe(true);
    expect(draft.fields.issuedDate.evidence.map(item=>item.text).join(" ")).not.toContain("02/03");
    expect(draft.fields.arcDocCode.evidence[0]).toMatchObject({coordinateSystem:native ? "pdf_points" : "raster_pixels"});
    expect(JSON.stringify(raw)).toBe(snapshot);
  });
  test("long subject can cross the old header fraction without taking body references", () => {
    const raw=fastMetadataDocument({native:true});
    const page=raw.pages[0], anchor=page.lines.find(line=>line.text==="NGHỊ ĐỊNH");
    page.lines=page.lines.filter(line=>!line.text.startsWith("Căn cứ")&&!line.text.startsWith("Điều 1")&&line.bbox[1]<=anchor.bbox[1]);
    const parts=Array.from({length:10},(_,i)=>`Dòng trích yếu độc lập ${i+1}${i===5 ? " ngày 19 tháng 9 năm 2021" : ""}`);
    parts.forEach((text,i)=>page.lines.push({text,line_index:20+i,bbox:[100,180+i*21,550,195+i*21],geometry_source:"native_text"}));
    page.lines.push({text:"Căn cứ Luật;",line_index:31,bbox:[45,420,555,435],geometry_source:"native_text"});
    expect(createDocumentDraft(raw).fields.subject.value).toBe(parts.join(" "));
  });
  test("expanded ROI can contain a genuine header below 45 percent of the page", () => {
    const raw=fastMetadataDocument({native:true}),page=raw.pages[0];
    page.roi=[0,0,page.width,page.height*.8];
    for(const line of page.lines) if(!line.metadata_excluded_reason) {
      line.bbox[1]+=page.height*.37;line.bbox[3]+=page.height*.37;
    }
    const values=documentValues(createDocumentDraft(raw));
    expect(values).toMatchObject({arcDocCode:"00042/2025/NĐ-QA",organName:"ỦY BAN NHÂN DÂN TỈNH KIỂM THỬ",issuedDate:"14-02-2025",subject:DECREE_SUBJECT,numberOfPage:"6"});
  });
  test("does not repair a stamp merged into the actual OCR subject line", () => {
    const raw=fastMetadataDocument({stamp:true});
    const line=raw.pages[0].lines.find(item=>item.text.startsWith("Quy định việc"));
    line.text="ngay. 99/99/2025, "+line.text;
    const draft=createDocumentDraft(raw);
    expect(draft.fields.subject.value).toContain("ngay. 99/99/2025,");
    expect(draft.fields.subject.status).toBe("review");
    expect(draft.fields.subject.evidence.some(item=>item.text===line.text)).toBe(true);
  });
  test("never derives full source count from the one processed page in a malformed partial result", () => {
    const raw=fastMetadataDocument(); delete raw.source_page_count;
    expect(createDocumentDraft(raw).fields.numberOfPage.value).toBe("");
  });
  test("does not invent a title/code for a cover or appendix", () => {
    const raw=fastMetadataDocument({native:true});
    raw.pages[0].lines=[{text:"PHỤ LỤC",line_index:1,bbox:[220,50,380,70],geometry_source:"native_text"},
      {text:"Số: 999/REF",line_index:2,bbox:[45,95,250,110],geometry_source:"native_text"},
      {text:"NGHỊ ĐỊNH",line_index:3,bbox:[180,140,400,160],geometry_source:"native_text"}];
    const values=documentValues(createDocumentDraft(raw));
    expect(values.arcDocCode).toBe(""); expect(values.typeName).toBe(""); expect(values.subject).toBe("");
  });
});

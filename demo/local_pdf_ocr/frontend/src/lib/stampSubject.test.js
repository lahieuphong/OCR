import {describe,expect,test} from "vitest";
import {confirmDocumentField,createDocumentDraft,documentValues,editDocumentField,FIELD_KEYS,serializeDocumentFields} from "./documentFields.js";
import {STAMP_TEST_SUBJECT,stampSubjectDocument} from "../test/fixtures/stampSubject.js";

function rewrite(raw) {
  raw.pages[0].text=raw.pages[0].lines.map(line=>line.text).join("\n");raw.text=raw.pages[0].text;
  return raw;
}
describe("conservative stamp-contaminated subject",()=>{
  test.each([false,true])("a stamp date cell read on the subject's first line is split off; the subject is filled for review (native=%s)",native=>{
    const raw=stampSubjectDocument({native,stamp:true,merged:true}),snapshot=JSON.stringify(raw),draft=createDocumentDraft(raw);
    const subject=draft.fields.subject;
    expect(subject.value).toBe(STAMP_TEST_SUBJECT);expect(subject.status).toBe("review");expect(subject.candidate).toBeUndefined();
    expect(subject.note).toMatch(/Dấu công văn đến chạm/u);expect(subject.note).toContain("Ô “Ngày: 03/02/2025,” của dấu");
    expect(subject.evidence.some(item=>item.text==="ĐẾN")).toBe(true);
    expect(subject.evidence.some(item=>item.text==="Ngày: 03/02/2025," && item.precision==="block")).toBe(true);
    expect(subject.evidence.every(item=>!item.text.startsWith("Căn cứ"))).toBe(true);
    const saved=JSON.parse(serializeDocumentFields(draft));expect(saved.subject).toBe(STAMP_TEST_SUBJECT);
    expect(JSON.stringify(saved)).not.toContain("Ngày: 03/02/2025");
    expect(confirmDocumentField(draft,"subject").fields.subject.status).toBe("confirmed");
    expect(JSON.stringify(raw)).toBe(snapshot);
  });
  test.each([false,true])("stamp text that cannot be separated remains evidence, never an export value (native=%s)",native=>{
    const raw=stampSubjectDocument({native,stamp:true,merged:"mixed"}),snapshot=JSON.stringify(raw),draft=createDocumentDraft(raw);
    expect(draft.fields.subject.value).toBe("");expect(draft.fields.subject.status).toBe("review");
    expect(draft.fields.subject.candidate).toContain("Ngày: 03/02/2025 giờ 9,");
    expect(draft.fields.subject.candidate).toContain(STAMP_TEST_SUBJECT);
    expect(draft.fields.subject.note).toMatch(/chưa xác minh.*dấu/iu);
    expect(draft.fields.subject.evidence.some(item=>item.text==="ĐẾN")).toBe(true);
    expect(draft.fields.subject.evidence.some(item=>item.text.startsWith("Ngày:"))).toBe(true);
    expect(draft.fields.subject.evidence.every(item=>!item.text.startsWith("Căn cứ"))).toBe(true);
    expect(documentValues(draft)).toMatchObject({arcDocCode:"00042/2025/NĐ-QA",issuedDate:"14-02-2025",organName:"ỦY BAN NHÂN DÂN TỈNH KIỂM THỬ",numberOfPage:"6",typeName:"NĐ",subject:""});
    const saved=JSON.parse(serializeDocumentFields(draft));expect(Object.keys(saved)).toEqual(FIELD_KEYS);expect(saved.subject).toBe("");
    expect(JSON.stringify(saved)).not.toContain("Ngày: 03/02/2025");
    expect(confirmDocumentField(draft,"subject")).toBe(draft);
    expect(confirmDocumentField(draft,"subject").fields.subject.status).toBe("review");
    const manual=editDocumentField(draft,"subject",STAMP_TEST_SUBJECT);
    expect(manual.fields.subject.status).toBe("confirmed");expect(documentValues(manual).subject).toBe(STAMP_TEST_SUBJECT);
    expect(JSON.stringify(raw)).toBe(snapshot);
  });
  test("a subject line overlapping a stamp read on its own lines is filled, for visual review",()=>{
    const raw=stampSubjectDocument({native:true,stamp:true});
    raw.pages[0].lines.find(line=>line.text.startsWith("Quy định việc")).bbox[0]=80;
    const subject=createDocumentDraft(rewrite(raw)).fields.subject;
    expect(subject.value).toBe(STAMP_TEST_SUBJECT);expect(subject.candidate).toBeUndefined();expect(subject.status).toBe("review");
    expect(subject.note).toMatch(/Dấu công văn đến chạm/u);expect(subject.evidence.some(item=>item.text==="Giờ: C")).toBe(true);
  });
  test("a short narrow merged date/subject line is evidence, never a disposable stamp field",()=>{
    const raw=stampSubjectDocument({native:true,stamp:true}),line=raw.pages[0].lines.find(item=>item.text.startsWith("Quy định việc"));
    line.text="Ngày: 03/02/2025, Tiếp nhận hồ sơ";line.bbox=[40,175,200,190];
    const subject=createDocumentDraft(rewrite(raw)).fields.subject;
    expect(subject.value).toBe("");expect(subject.candidate).toContain(line.text);expect(subject.evidence.some(item=>item.text===line.text)).toBe(true);
  });
  test("a lone mixed orphan keeps its candidate and evidence when no paragraph continuation is usable",()=>{
    const raw=stampSubjectDocument({native:true,stamp:true}),page=raw.pages[0],line=page.lines.find(item=>item.text.startsWith("Quy định việc"));
    line.text="Ngày: 03/02/2025, Tiếp nhận hồ sơ";line.bbox=[40,175,200,190];
    page.lines=page.lines.filter(item=>item.bbox[1]<195 || item.bbox[1]>250);
    const subject=createDocumentDraft(rewrite(raw)).fields.subject;
    expect(subject.value).toBe("");expect(subject.status).toBe("review");expect(subject.candidate).toBe(line.text);
    expect(subject.evidence.some(item=>item.text===line.text)).toBe(true);expect(subject.evidence.some(item=>item.text==="ĐẾN")).toBe(true);
  });
  test("very close stamp/subject boxes are not treated as certain segmentation",()=>{
    const raw=stampSubjectDocument({native:true,stamp:true});
    raw.pages[0].lines.find(line=>line.text.startsWith("Quy định việc")).bbox[0]=91;
    const subject=createDocumentDraft(rewrite(raw)).fields.subject;
    expect(subject.value).toBe(STAMP_TEST_SUBJECT);expect(subject.status).toBe("review");expect(subject.note).toMatch(/chữ sát dấu/u);
  });
  test("stamp geometrically separate from the paragraph does not blank a clean long subject",()=>{
    const draft=createDocumentDraft(stampSubjectDocument({native:true,stamp:true}));
    expect(draft.fields.subject.value).toBe(STAMP_TEST_SUBJECT);expect(draft.fields.subject.candidate).toBeUndefined();
  });
  test("legitimate word đến in a subject is preserved",()=>{
    const raw=stampSubjectDocument({native:true});raw.pages[0].lines.find(line=>line.text.startsWith("Quy định việc")).text="Kế hoạch vận chuyển đến địa phương và tiếp tục thực hiện";
    expect(createDocumentDraft(rewrite(raw)).fields.subject.value).toContain("đến địa phương");
  });
  test("an isolated exact word ĐẾN is not removed without a stamp cluster",()=>{
    const raw=stampSubjectDocument({native:true});raw.pages[0].lines.find(line=>line.text.startsWith("Quy định việc")).text="ĐẾN";
    expect(createDocumentDraft(rewrite(raw)).fields.subject.value).toMatch(/^ĐẾN /u);
  });
  test("unrelated date in the other header column cannot turn isolated ĐẾN into a stamp",()=>{
    const raw=stampSubjectDocument({native:true});raw.pages[0].lines.find(line=>line.text.startsWith("Quy định việc")).text="ĐẾN";
    raw.pages[0].lines.find(line=>line.text.startsWith("Nơi thử nghiệm")).text="Ngày: 03/02/2025";
    expect(createDocumentDraft(rewrite(raw)).fields.subject.value).toMatch(/^ĐẾN /u);
  });
  test("a nearby arrival stamp never consumes the administrative document number",()=>{
    const raw=stampSubjectDocument({native:true,stamp:true}),lines=raw.pages[0].lines;
    const arrival=lines.find(line=>line.text==="ĐẾN"),time=lines.find(line=>line.text==="Giờ: C");
    arrival.bbox=[5,118,90,133];time.bbox=[5,138,90,151];
    expect(createDocumentDraft(rewrite(raw)).fields.arcDocCode.value).toBe("00042/2025/NĐ-QA");
  });
  test.each(["native_text","vietocr_ocr","hybrid_h1"])("stamp safety preserves literal raw %s exports",method=>{
    for (const merged of [true,"mixed"]) {
      const raw=stampSubjectDocument({native:method==="native_text",stamp:true,merged});raw.method=method;
      const before=JSON.stringify(raw);const draft=createDocumentDraft(raw);
      if (merged===true) {expect(draft.fields.subject.value).toBe(STAMP_TEST_SUBJECT);expect(draft.fields.subject.status).toBe("review");}
      else {expect(draft.fields.subject.value).toBe("");expect(draft.fields.subject.candidate).toContain("Ngày:");}
      expect(JSON.stringify(raw)).toBe(before);
    }
  });
});

describe("handwriting inside an arrival stamp",()=>{
  const withTime=text=>{
    const raw=stampSubjectDocument({native:true,stamp:true});
    raw.pages[0].lines.find(line=>line.text==="Giờ: C").text=text;
    return createDocumentDraft(rewrite(raw)).fields.subject;
  };
  test.each(["Giờ: 0G/9:2D","Giờ: S","Giờ:"])("a stamp field read as noise (%s) is the stamp, not part of the subject",text=>{
    const subject=withTime(text);
    expect(subject.value).toBe(STAMP_TEST_SUBJECT);expect(subject.candidate).toBeUndefined();
  });
  test("a stamp field holding words stays mixed evidence",()=>{
    const subject=withTime("Giờ: 9 giờ Quy định");
    expect(subject.value).toBe("");expect(subject.status).toBe("review");expect(subject.candidate).toContain("Giờ: 9 giờ Quy định");
  });
});

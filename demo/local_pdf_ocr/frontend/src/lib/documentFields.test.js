import {describe, expect, test} from "vitest";
import {CATALOGS, FIELD_KEYS, createDocumentDraft, documentValues, editDocumentField, confirmDocumentField,
  isValidIssuedDate, serializeDocumentFields, validateDocumentDraft} from "./documentFields.js";
import {documentFromRows, syntheticDocument, SYNTHETIC_CASES} from "../test/fixtures/administrativeDocuments.js";
import {SYNTHETIC_GOLD} from "../test/fixtures/metadataGold.js";

const draft = options => createDocumentDraft(syntheticDocument(options));
const value = (d, key) => d.fields[key].value;
const freeze = obj => {Object.freeze(obj); Object.values(obj).forEach(v => {if (v && typeof v === "object") freeze(v);}); return obj;};

describe("business schema and provenance", () => {
  test.each(Object.keys(SYNTHETIC_GOLD))("matches all 22 hand-authored synthetic fields for %s", name => {
    expect(JSON.parse(serializeDocumentFields(createDocumentDraft(SYNTHETIC_CASES[name])))).toEqual(SYNTHETIC_GOLD[name]);
  });
  test("exports exactly the specified 22 keys, all strings, with no audit keys", () => {
    const expected = ["docId","arcDocCode","maintenance","typeName","codeNumber","codeNotation","issuedDate","organName","subject","language","numberOfPage","inforSign","keyword","mode","confidenceLevel","autograph","format","process","riskRecovery","riskRecoveryStatus","description","isCan"];
    const parsed = JSON.parse(serializeDocumentFields(draft()));
    expect(Object.keys(parsed)).toEqual(expected);
    expect(Object.keys(parsed)).toEqual(FIELD_KEYS);
    expect(Object.values(parsed).every(v => typeof v === "string")).toBe(true);
    expect(parsed.docId).toBe(""); expect(parsed.codeNumber).toBe("00103");
    expect(parsed.typeName).toBe("22"); expect(parsed.language).toBe("01");
  });
  test("does not mutate nested OCR geometry, text, reading order or raw JSON bytes", () => {
    const raw = freeze(syntheticDocument({method: "vietocr_ocr"}));
    const bytes = JSON.stringify(raw, null, 2);
    let d = createDocumentDraft(raw);
    d = editDocumentField(d, "subject", "Trích yếu sửa thủ công Đặng Văn A");
    serializeDocumentFields(d);
    expect(JSON.stringify(raw, null, 2)).toBe(bytes);
    expect(d.fields.arcDocCode.evidence[0]).toMatchObject({page: 1, line: 4, coordinateSystem: "raster_pixels", precision: "polygon"});
  });
  test.each(["vietocr_ocr", "hybrid_h1"])("%s text requires visual review without calibrated confidence", method => {
    const d = draft({method});
    for (const key of ["arcDocCode","codeNumber","codeNotation","issuedDate","organName","subject","typeName","language"]) expect(d.fields[key].status).toBe("review");
    expect(d.fields.numberOfPage.status).toBe("recognized");
  });
  test("empty text does not manufacture content, language, classification or stamp color", () => {
    const d = createDocumentDraft(SYNTHETIC_CASES.unreadableScan);
    for (const key of FIELD_KEYS.filter(k => !["confidenceLevel", "numberOfPage"].includes(k))) expect(value(d, key)).toBe("");
    expect(value(d, "numberOfPage")).toBe("1");
    expect(value(d, "confidenceLevel")).toBe("02"); expect(d.fields.confidenceLevel.status).toBe("review");
  });
  test("manual-only fields remain empty and no file name is used as evidence", () => {
    const raw = {...syntheticDocument(), filename: "QUYET_DINH_999_01-01-2000.pdf"};
    const d = createDocumentDraft(raw);
    for (const key of ["maintenance","inforSign","keyword","mode","autograph","format","process","riskRecovery","riskRecoveryStatus","description","isCan"]) expect(value(d, key)).toBe("");
    expect(value(d, "issuedDate")).toBe("08-10-2026");
  });
  test("does not invent 29 missing document type codes", () => {
    expect(Object.keys(CATALOGS.typeName)).toEqual(["22", "01", "02"]);
    expect(value(draft({kind: "THÔNG BÁO"}), "typeName")).toBe("");
    expect(validateDocumentDraft(editDocumentField(draft(), "typeName", "32")).errors.typeName).toBeTruthy();
  });
});

describe("header extraction", () => {
  test.each(["native_text", "vietocr_ocr"])("handles two-column headers using %s geometry", method => {
    const d = draft({method});
    expect(value(d, "organName")).toBe("VĂN PHÒNG KIỂM THỬ");
    expect(value(d, "subject")).toBe("kiểm thử trích xuất thông tin trên tài liệu tổng hợp, giữ nguyên tiếng Việt");
    expect(value(d, "arcDocCode")).toBe("00103/TEST-CN");
    expect(value(d, "issuedDate")).toBe("08-10-2026");
  });
  test.each([["10300/VPCP-CN","10300","VPCP-CN"],["321/NQ-CP","321","NQ-CP"],["001/A/B-C","001","B-C"],["001/TEST‐CN","001","TEST‐CN"]])("preserves all slashes and hyphens in %s", (code, number, notation) => {
    const d = draft({code});
    expect(value(d,"arcDocCode")).toBe(code); expect(value(d,"codeNumber")).toBe(number); expect(value(d,"codeNotation")).toBe(notation);
  });
  test.each([["Số:","00103 / TEST-CN"],["Số : 00103/","TEST-CN"],["Số：00103", "/TEST-CN"]])("supports wrapped number label %s", (a,b) => {
    const d = createDocumentDraft(documentFromRows([[a,45,95,260,108],[b,45,112,260,127],["Căn cứ số 999/QĐ-BODY",45,260,555,275]]));
    expect(value(d,"arcDocCode")).toBe("00103/TEST-CN");
  });
  test("never replaces ambiguous OCR characters", () => {
    const d = createDocumentDraft(SYNTHETIC_CASES.ambiguousCode);
    expect(value(d,"arcDocCode")).toBe("1O3?0/TEST-CN"); expect(d.fields.arcDocCode.status).toBe("review");
  });
  test("does not truncate an ambiguous notation separated by spaces", () => {
    const d = draft({code: "00103/TEST CN"});
    expect(value(d,"arcDocCode")).toBe(""); expect(d.fields.arcDocCode.status).toBe("review");
  });
  test("does not pick cited body numbers or dates even near the top", () => {
    const d = createDocumentDraft(documentFromRows([["Căn cứ Quyết định số 999/QĐ-BODY ngày 01 tháng 01 năm 2020;",45,100,555,115],["Số: 777/REF",45,125,300,140]]));
    expect(value(d,"arcDocCode")).toBe(""); expect(value(d,"issuedDate")).toBe("");
  });
  test("does not pick citations on later pages", () => {
    const raw = syntheticDocument({code:null,pages:2});
    raw.pages[1].lines = [{line_index:1,text:"Số: 999/QĐ-BODY",bbox:[50,50,350,70]}];
    expect(value(createDocumentDraft(raw),"arcDocCode")).toBe("");
  });
  test("does not treat an issuance date quoted in a subject as the current date", () => {
    const raw = syntheticDocument();
    raw.pages[0].lines[4].text = "Không rõ ngày ban hành";
    raw.pages[0].lines[6].text = "V/v thực hiện văn bản ngày 01 tháng 01 năm 2020";
    expect(value(createDocumentDraft(raw),"issuedDate")).toBe("");
  });
  test("does not take a number below the title when no body marker is present", () => {
    const raw = documentFromRows([["QUYẾT ĐỊNH",175,100,420,118],["Về việc kiểm thử",130,140,460,155],["Số: 777/REF",45,230,300,245]]);
    expect(value(createDocumentDraft(raw),"arcDocCode")).toBe("");
  });
  test("does not join a separate body paragraph to the subject", () => {
    const raw = syntheticDocument();
    raw.pages[0].lines[8].text = "Đoạn nội dung độc lập, không phải trích yếu.";
    expect(value(createDocumentDraft(raw),"subject")).not.toContain("Đoạn nội dung độc lập");
  });
  test("conflicting identifiers and agency headers stay unresolved", () => {
    const d = draft({extra:[["Số: 777/OTHER",45,120,260,135]]});
    expect(value(d,"arcDocCode")).toBe(""); expect(d.fields.arcDocCode.status).toBe("review");
    const agencies = createDocumentDraft(documentFromRows([["BỘ KIỂM THỬ",45,35,270,50],["SỞ TỔNG HỢP",45,58,270,72],["Số: 01/TEST",45,95,260,110]]));
    expect(value(agencies,"organName")).toBe("");
  });
  test("an incomplete competing number is not silently discarded", () => {
    expect(value(draft({extra:[["Số: ???",45,120,260,135]]}),"arcDocCode")).toBe("");
  });
  test("national motto is never the issuing agency", () => {
    const raw = syntheticDocument(); raw.pages[0].lines.shift();
    expect(value(createDocumentDraft(raw),"organName")).toBe("");
  });
  test.each([["CÔNG VĂN","22"],["QUYẾT ĐỊNH","02"],["NGHỊ QUYẾT","01"],["KHÔNG RÕ",""]])("uses explicit title %s", (kind, code) => expect(value(draft({kind}),"typeName")).toBe(code));
  test("V/v alone does not imply official-letter classification", () => {
    expect(value(draft({kind:""}),"typeName")).toBe("");
  });
  test("requires clear language evidence and leaves bilingual documents unresolved", () => {
    const english = documentFromRows([["GOVERNMENT OF TEST",45,35,270,50],["DECISION FOR THE ADMINISTRATIVE DOCUMENT",100,140,500,158]]);
    expect(value(createDocumentDraft(english),"language")).toBe("02");
    const bilingual = syntheticDocument();
    bilingual.pages[0].lines.push({text:"DECISION FOR THE DOCUMENT",line_index:99,bbox:[100,500,500,520]});
    expect(value(createDocumentDraft(bilingual),"language")).toBe("");
  });
  test("falls back to literal page text without fabricating coordinates", () => {
    const raw = syntheticDocument(); delete raw.pages[0].lines;
    const d = createDocumentDraft(raw);
    expect(value(d,"arcDocCode")).toBe("00103/TEST-CN"); expect(d.fields.arcDocCode.evidence[0].bounds).toBeUndefined();
  });
});

describe("dates, page counts and manual drafts", () => {
  test.each([["29-02-2024",true],["29-02-2025",false],["31-04-2026",false],["08-10-2026",true],["00-10-2026",false],["1-1-2026",false]])("checks %s with the UTC calendar", (date, valid) => expect(isValidIssuedDate(date)).toBe(valid));
  test("invalid and competing header dates stay empty", () => {
    expect(value(draft({date:"31 tháng 02 năm 2026"}),"issuedDate")).toBe("");
    expect(value(createDocumentDraft(SYNTHETIC_CASES.competingDates),"issuedDate")).toBe("");
  });
  test("PDF count comes from the source reader, image count is one, not a printed footer", () => {
    expect(value(draft({pages:6}),"numberOfPage")).toBe("6");
    expect(value(createDocumentDraft(syntheticDocument(),{sourceKind:"image"}),"numberOfPage")).toBe("1");
    expect(value(createDocumentDraft({...syntheticDocument(),page_count:99}),"numberOfPage")).toBe("");
  });
  test.each([["0","01"],["1","02"],["","02"]])("derives business confidence from isCan=%s", (stamp, code) => {
    expect(documentValues(editDocumentField(draft(),"isCan",stamp)).confidenceLevel).toBe(code);
  });
  test("edits and confirmations preserve prior drafts, mode isolation and Unicode", () => {
    const original = draft(), ocr = draft({method:"vietocr_ocr",code:"88/OCR"});
    const edited = editDocumentField(original,"subject","Đã sửa: Nguyễn Văn A\nDòng hai.");
    const confirmed = confirmDocumentField(edited,"arcDocCode");
    expect(value(original,"subject")).not.toBe(value(edited,"subject")); expect(confirmed.dirty).toBe(true);
    expect(confirmed.fields.arcDocCode.status).toBe("confirmed"); expect(value(ocr,"arcDocCode")).toBe("88/OCR");
    expect(JSON.parse(serializeDocumentFields(confirmed)).subject).toBe("Đã sửa: Nguyễn Văn A\nDòng hai.");
  });
  test("cannot edit docId, counts or other derived fields directly", () => {
    const d = draft(); expect(editDocumentField(d,"docId","invented")).toBe(d);
    expect(editDocumentField(d,"numberOfPage","100")).toBe(d);
  });
  test("confirming an OCR identifier also confirms its read-only derived parts", () => {
    const d = confirmDocumentField(draft({method:"vietocr_ocr"}),"arcDocCode");
    for (const key of ["arcDocCode","codeNumber","codeNotation"]) expect(d.fields[key].status).toBe("confirmed");
  });
  test("identifier edits update dependent fields and invalid dates prevent export", () => {
    const d = editDocumentField(draft(),"arcDocCode","00007/A/B-C");
    expect(value(d,"codeNumber")).toBe("00007"); expect(value(d,"codeNotation")).toBe("B-C");
    expect(() => serializeDocumentFields(editDocumentField(d,"issuedDate","31-02-2026"))).toThrow();
  });
  test("unclassified mode is preserved empty and flagged before export", () => {
    const d = draft(); expect(validateDocumentDraft(d).unclassifiedMode).toBe(true);
    expect(JSON.parse(serializeDocumentFields(d)).mode).toBe("");
  });
});

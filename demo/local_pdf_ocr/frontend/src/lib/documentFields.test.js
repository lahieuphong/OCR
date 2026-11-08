import {describe, expect, test} from "vitest";
import {CATALOGS, FIELD_KEYS, PROVISIONAL_TYPE_CODES, TYPE_CODES, createDocumentDraft, documentValues, editDocumentField, confirmDocumentField,
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
  test("keeps the official type codes and adds only the owner's marked provisional codes", () => {
    expect(CATALOGS.typeName).toEqual({"01": "Nghị quyết", "02": "Quyết định", "22": "Công văn",
      "NĐ": "Nghị định (mã tạm)", "TB": "Thông báo (mã tạm)", "TT": "Thông tư (mã tạm)"});
    expect([...PROVISIONAL_TYPE_CODES]).toEqual(["NĐ", "TB", "TT"]);
    expect(TYPE_CODES.filter(entry => entry.provisional).every(entry => entry.official === null && Object.isFrozen(entry))).toBe(true);
    const notice = draft({kind: "THÔNG BÁO"});
    expect(value(notice, "typeName")).toBe("TB"); expect(notice.fields.typeName.status).toBe("review");
    expect(value(draft({kind: "BÁO CÁO"}), "typeName")).toBe("");
    expect(validateDocumentDraft(editDocumentField(draft(), "typeName", "NĐ")).errors.typeName).toBeUndefined();
    expect(validateDocumentDraft(editDocumentField(draft(), "typeName", "32")).errors.typeName).toBeTruthy();
  });
});

describe("header extraction", () => {
  test.each(["native_text", "vietocr_ocr"])("handles two-column headers using %s geometry", method => {
    const d = draft({method});
    expect(value(d, "organName")).toBe("VĂN PHÒNG KIỂM THỬ");
    expect(value(d, "subject")).toBe("V/v kiểm thử trích xuất thông tin trên tài liệu tổng hợp, giữ nguyên tiếng Việt");
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

// Synthetic rows in PDF points (595 x 842), modelled on layouts seen in real headers; no real document text.
const IDENTITY = [["VĂN PHÒNG KIỂM THỬ",45,35,270,50],["CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM",320,35,570,50],["Độc lập - Tự do - Hạnh phúc",350,60,560,75]];
const rowsDraft = (rows, method = "native_text") => createDocumentDraft(documentFromRows(rows, {method}));
const decision = (subject, extra = []) => [...IDENTITY, ["Số: 12/QĐ-KT",90,95,230,110], ["Hà Nội, ngày 08 tháng 10 năm 2026",320,95,570,110],
  ["QUYẾT ĐỊNH",240,140,355,158], ...subject, ...extra, ["Căn cứ Luật Kiểm thử;",45,300,555,315]];

describe("header rules for real layouts", () => {
  test("an official letter is recognised from its layout: V/v under the number, no title", () => {
    const d = rowsDraft([...IDENTITY, ["Số: 10300/VPCP-CN",110,95,235,110], ["Hà Nội, ngày 08 tháng 10 năm 2026",320,95,570,110],
      ["V/v triển khai kết luận của Bộ",100,115,250,128], ["Kính gửi: Bộ Kiểm thử",200,160,400,175]]);
    expect(value(d, "typeName")).toBe("22"); expect(d.fields.typeName.status).toBe("review"); expect(d.typeLabel).toBe("Công văn");
    expect(d.fields.typeName.evidence.map(source => source.text)).toEqual(["Số: 10300/VPCP-CN", "V/v triển khai kết luận của Bộ"]);
  });
  test("a consolidated text does not take the type of the act it consolidates", () => {
    const d = createDocumentDraft(documentFromRows([["VĂN BẢN HỢP NHẤT", 90, 68, 230, 84], ["CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", 260, 52, 560, 68],
      ["Số: 15/2026/VBHN-TT-KT", 70, 96, 250, 111], ["Hà Nội, ngày 08 tháng 10 năm 2026", 310, 96, 520, 111],
      ["THÔNG TƯ", 270, 136, 350, 151], ["Quy định về kiểm thử hợp nhất", 150, 153, 450, 168], ["Căn cứ Luật Kiểm thử;", 100, 200, 500, 215]]));
    expect(value(d, "typeName")).toBe(""); expect(d.fields.typeName.status).toBe("review");
    expect(d.fields.typeName.note).toContain("Văn bản hợp nhất"); expect(value(d, "arcDocCode")).toBe("15/2026/VBHN-TT-KT");
  });
  test("a circular gets the provisional code TT, for review", () => {
    const d = draft({kind: "THÔNG TƯ"});
    expect(d.typeLabel).toBe("Thông tư"); expect(value(d, "typeName")).toBe("TT"); expect(d.fields.typeName.status).toBe("review");
    expect(d.fields.typeName.note).toContain("Mã tạm “TT”");
  });
  test("the signing portal's agency mark does not compete with the issuing agency", () => {
    const d = rowsDraft(decision([["Phê duyệt nội dung kiểm thử",150,175,450,190]], [["Cơ quan phát hành: Văn phòng Kiểm thử",45,55,270,67]]));
    expect(value(d, "organName")).toBe("VĂN PHÒNG KIỂM THỬ");
  });
  test("the agency is taken from a line where the detector merged both header columns", () => {
    const rows = decision([["Phê duyệt nội dung kiểm thử",150,175,450,190]]);
    rows.splice(0, 2, ["THỦ TƯỚNG CHÍNH PHỦ CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM",45,35,570,50]);
    expect(value(rowsDraft(rows, "vietocr_ocr"), "organName")).toBe("THỦ TƯỚNG CHÍNH PHỦ");
  });
  test("lower-case agency words inside a subject do not end it", () => {
    const d = rowsDraft(decision([["Phê duyệt kế hoạch phối hợp của Liên",150,175,450,190], ["bộ và Trường Đại học Kiểm thử",150,193,450,208]]));
    expect(value(d, "subject")).toBe("Phê duyệt kế hoạch phối hợp của Liên bộ và Trường Đại học Kiểm thử");
  });
  test("a paragraph after the subject (consolidated text preamble) is not part of it", () => {
    const subject = [["Quy định về biểu mẫu kiểm thử và",150,175,450,190], ["sổ kiểm thử cấp cho đơn vị",150,191,450,206], ["kiểm thử nội địa",200,207,400,222],
      ["Thông tư số 20/2022/TT-KT ngày 29 tháng 7 năm 2022 của Bộ trưởng",100,239,500,254], ["được sửa đổi, bổ sung bởi:",80,255,300,270]];
    const d = rowsDraft(decision(subject));
    expect(value(d, "subject")).toBe("Quy định về biểu mẫu kiểm thử và sổ kiểm thử cấp cho đơn vị kiểm thử nội địa");
    const even = rowsDraft(decision(subject.slice(0, 3).concat([["và thêm một dòng cách đều",150,223,450,238]])));
    expect(value(even, "subject")).toBe("Quy định về biểu mẫu kiểm thử và sổ kiểm thử cấp cho đơn vị kiểm thử nội địa và thêm một dòng cách đều");
  });
  test("ruling lines and underscores are not text", () => {
    const d = rowsDraft(decision([["Phê duyệt nội dung kiểm thử",150,175,450,190], ["______________",240,193,355,200]]));
    expect(value(d, "subject")).toBe("Phê duyệt nội dung kiểm thử");
  });
  test("a bare Số: label takes its value from the next line or from the same row", () => {
    const below = decision([["Phê duyệt nội dung kiểm thử",150,175,450,190]]);
    below.splice(3, 1, ["Số:",90,95,112,110], ["00042/2025/NĐ-KT",90,112,230,126]);
    expect(value(rowsDraft(below), "arcDocCode")).toBe("00042/2025/NĐ-KT");
    const sameRow = decision([["Phê duyệt nội dung kiểm thử",150,175,450,190]]);
    // The value's box starts higher, so the detector lists it before its label.
    sameRow.splice(3, 1, ["637/QĐ-TTg",118,93,200,110], ["Số:",90,95,112,110]);
    expect(value(rowsDraft(sameRow, "vietocr_ocr"), "arcDocCode")).toBe("637/QĐ-TTg");
  });
  test.each([["3ố: 1157/QĐ-TTg", "1157/QĐ-TTg", "3ố"], ["Ố: 180/TB-VPCP", "180/TB-VPCP", "Ố"]])("a misread Số label %s keeps the value as read, for review", (line, code, label) => {
    const rows = decision([["Phê duyệt nội dung kiểm thử",150,175,450,190]]);
    rows.splice(3, 1, [line,90,95,230,110]);
    const d = rowsDraft(rows, "vietocr_ocr");
    expect(value(d, "arcDocCode")).toBe(code); expect(d.fields.arcDocCode.status).toBe("review");
    expect(d.fields.arcDocCode.note).toContain(`“${label}”`);
  });
  test("a number read with a space between its digits is joined, for review", () => {
    const rows = decision([["Phê duyệt nội dung kiểm thử",150,175,450,190]]);
    rows.splice(3, 1, ["Số: 2 1/2026/TT-BCT",90,95,230,110]);
    const d = rowsDraft(rows, "vietocr_ocr");
    expect(value(d, "arcDocCode")).toBe("21/2026/TT-BCT"); expect(value(d, "codeNumber")).toBe("21");
    expect(d.fields.arcDocCode.status).toBe("review"); expect(d.fields.arcDocCode.note).toContain("“2 1”");
    rows.splice(3, 1, ["Số: 21/2026/TT-BCT",90,95,230,110]);
    const plain = rowsDraft(rows);
    expect(value(plain, "arcDocCode")).toBe("21/2026/TT-BCT"); expect(plain.fields.arcDocCode.status).toBe("recognized");
  });
  test("a word ending in ố before other text is not a number label", () => {
    const rows = decision([["Phê duyệt nội dung kiểm thử",150,175,450,190]]);
    rows.splice(3, 1, ["Bố cục: 1/2",90,95,230,110]);
    expect(value(rowsDraft(rows), "arcDocCode")).toBe("");
  });
  test("a handwritten day read with a space between its digits is joined, for review", () => {
    const rows = decision([["Phê duyệt nội dung kiểm thử",150,175,450,190]]);
    rows.splice(4, 1, ["Hà Nội, ngày 0 7 tháng 4 năm 2026",320,95,570,110]);
    const d = rowsDraft(rows, "vietocr_ocr");
    expect(value(d, "issuedDate")).toBe("07-04-2026"); expect(d.fields.issuedDate.status).toBe("review");
    expect(d.fields.issuedDate.note).toContain("ngày 0 7 tháng 4");
    rows.splice(4, 1, ["Hà Nội, ngày 0 F tháng 4 năm 2026",320,95,570,110]);
    expect(value(rowsDraft(rows, "vietocr_ocr"), "issuedDate")).toBe("");
  });
});

describe("seal colour", () => {
  const withSeal = seal => createDocumentDraft({...syntheticDocument(), seal});
  test("a red round seal found on a page fills the seal colour and the confidence code", () => {
    const d = withSeal({method: "red_round_mark_v1", reason: "found", colour: "red", page: 2, size_mm: [40.4, 40.1], pages_checked: [3, 2]});
    expect(value(d, "isCan")).toBe("0"); expect(d.fields.isCan.status).toBe("recognized");
    expect(d.fields.isCan.evidence[0]).toMatchObject({source: "seal_colour", sealPage: 2, text: "Trang 2: dấu tròn màu đỏ khoảng 40 × 40 mm."});
    expect(value(d, "confidenceLevel")).toBe("01"); expect(documentValues(d).confidenceLevel).toBe("01");
  });
  test("a black-and-white scan or a missing seal leaves the colour unknown with a reason", () => {
    for (const [reason, text] of [["black_and_white", "đen trắng"], ["not_found", "2 trang"]]) {
      const d = withSeal({method: "red_round_mark_v1", reason, colour: null, pages_checked: [2, 1]});
      expect(value(d, "isCan")).toBe(""); expect(d.fields.isCan.status).toBe("unknown"); expect(d.fields.isCan.note).toContain(text);
      expect(documentValues(d).confidenceLevel).toBe("02");
    }
  });
  test("results without a seal check (older results, errors) keep the previous behaviour", () => {
    for (const seal of [undefined, {reason: "error", colour: null}, {reason: "found", colour: "red"}]) {
      const d = withSeal(seal);
      expect(value(d, "isCan")).toBe(""); expect(d.fields.isCan.note).toBe(""); expect(value(d, "confidenceLevel")).toBe("02");
    }
  });
});

describe("owner records, round 1", () => {
  // Hand-authored fictional text; geometry follows a scanned decision with a handwritten mark top right.
  const decision = ({mark = ["TTĐT(2)", 480, 25, 570, 62], extra = []} = {}) => documentFromRows([
    ...(mark ? [mark] : []),
    ["BỘ KIỂM THỬ", 80, 70, 230, 86], ["CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", 260, 70, 560, 86],
    ["Độc lập - Tự do - Hạnh phúc", 320, 88, 520, 102], ["Số: 12/QĐ-KT", 100, 115, 230, 130],
    ["Hà Nội, ngày 08 tháng 4 năm 2026", 300, 118, 520, 132], ["QUYẾT ĐỊNH", 270, 160, 370, 175],
    ["Về việc kiện toàn tổ kiểm thử", 150, 178, 450, 195], ["giữ nhiệm vụ thử nghiệm", 170, 196, 430, 212],
    ["BỘ TRƯỞNG BỘ KIỂM THỬ", 220, 230, 380, 246], ["Căn cứ Luật Kiểm thử;", 100, 260, 500, 276], ...extra]);
  test("a subject starting with “Về việc” under a title keeps it as printed", () => {
    expect(value(createDocumentDraft(decision()), "subject")).toBe("Về việc kiện toàn tổ kiểm thử giữ nhiệm vụ thử nghiệm");
  });
  test("the handwritten mark above the national motto, top right, is the Ký hiệu thông tin, for review", () => {
    const field = createDocumentDraft(decision()).fields.inforSign;
    expect(field.value).toBe("TTĐT(2)"); expect(field.status).toBe("review");
    expect(field.evidence.map(source => source.text)).toEqual(["TTĐT(2)"]); expect(field.note).toMatch(/viết tay/u);
  });
  test("a space read inside the mark is removed and reported", () => {
    const field = createDocumentDraft(decision({mark: ["TTĐ T", 480, 25, 570, 62]})).fields.inforSign;
    expect(field.value).toBe("TTĐT"); expect(field.note).toContain("“TTĐ T”");
  });
  test.each([["HỎA TỐC", 480, 25, 570, 62], ["Dự thảo", 480, 25, 570, 62], ["TTĐT", 480, 92, 570, 110], ["TTĐT", 300, 25, 400, 62]])(
    "%s (printed mark, or not above the motto in the top-right corner) is not taken", (...mark) => {
      expect(createDocumentDraft(decision({mark})).fields.inforSign).toMatchObject({value: "", status: "unknown"});
    });
  test("two marks in the corner are left to the reader", () => {
    const field = createDocumentDraft(decision({extra: [["CN", 470, 45, 520, 60]]})).fields.inforSign;
    expect(field).toMatchObject({value: "", status: "review"});
  });
  test("no mark leaves the field empty", () => {
    expect(createDocumentDraft(decision({mark: null})).fields.inforSign.value).toBe("");
  });
});

describe("owner decisions after round 2: access mode from the publication source", () => {
  // Hand-authored fictional header; the first rows are the PDF's visible electronic-signature block.
  const published = ({signer = "Người ký: CỔNG THÔNG TIN ĐIỆN TỬ CHÍNH PHỦ", email = "Email: thongtinchinhphu@chinhphu.vn", extra = [], signatureBlock = true} = {}) => {
    const raw = documentFromRows([[signer, 200, 5, 420, 15], [email, 200, 16, 420, 24],
      ["BỘ KIỂM THỬ", 80, 70, 230, 86], ["CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", 260, 70, 560, 86],
      ["Số: 12/QĐ-KT", 100, 115, 230, 130], ["Hà Nội, ngày 08 tháng 4 năm 2026", 300, 118, 520, 132],
      ["QUYẾT ĐỊNH", 270, 160, 370, 175], ["Về việc kiểm thử chế độ sử dụng", 150, 178, 450, 195],
      ["Căn cứ Luật Kiểm thử;", 100, 260, 500, 276], ...extra]);
    if (signatureBlock) raw.pages[0].lines.slice(0, 2).forEach(line => {line.metadata_excluded_reason = "electronic_signature";});
    return createDocumentDraft(raw);
  };
  test("a PDF signed by the Government portal for publication is 01 from that source, always for review", () => {
    const field = published().fields.mode;
    expect(field.value).toBe("01"); expect(field.status).toBe("review");
    expect(field.note).toContain("nguồn công bố"); expect(field.note).toContain("không phải xác nhận phân quyền nội bộ");
    expect(field.evidence.map(source => source.text)).toEqual(["Người ký: CỔNG THÔNG TIN ĐIỆN TỬ CHÍNH PHỦ", "Email: thongtinchinhphu@chinhphu.vn"]);
    expect(JSON.parse(serializeDocumentFields(published())).mode).toBe("01");
  });
  test("a secrecy mark on page 1 keeps it empty, for review", () => {
    const field = published({extra: [["MẬT", 60, 140, 100, 155]]}).fields.mode;
    expect(field).toMatchObject({value: "", status: "review"}); expect(field.note).toContain("độ mật");
  });
  test.each([
    ["another signer", {signer: "Ký bởi: Sở Kiểm thử", email: "Email: vanthu@kiemthu.vn"}],
    ["the portal address outside the signature block", {signatureBlock: false, signer: "Ghi chú thử nghiệm", email: "Liên hệ thongtinchinhphu@chinhphu.vn"}],
  ])("%s leaves it empty, marked for verification", (_name, options) => {
    const d = published(options);
    expect(d.fields.mode).toMatchObject({value: "", status: "review"}); expect(d.fields.mode.note).toContain("cần xác minh");
    expect(validateDocumentDraft(d).unclassifiedMode).toBe(true);
  });
});

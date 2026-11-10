import {describe, expect, test} from "vitest";
import {createDocumentDraft, documentValues} from "./documentFields.js";
import {partialScope, validateFastResult} from "./processingModes.js";

// Round 6 (owner, 2026-11-10): a consolidated text whose page 1 has no header of its own (no agency, no "Số" above
// the title) carries its number, date and authenticating body in the "XÁC THỰC VĂN BẢN HỢP NHẤT" block where its
// main text ends. Synthetic rows; layout modelled on that block, no real document text.
const quad = ([x0, y0, x1, y1]) => [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
const ocrLine = (text, box, index) => ({text, line_index: index, polygon: quad(box), geometry_source: "vietocr_ocr"});
const nativeLine = (text, box, index) => ({text, line_index: index, bbox: box, geometry_source: "native_text"});
const PAGE_ONE = [
  ["CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", [600, 100, 1100, 125]], ["Độc lập - Tự do - Hạnh phúc", [700, 135, 1000, 160]],
  ["THÔNG TƯ", [560, 220, 670, 245]], ["Quy định về kiểm thử hợp nhất", [400, 260, 830, 285]],
  ["Thông tư số 01/2020/TT-BKT ngày 02 tháng 3 năm 2020 của Bộ trưởng", [260, 360, 1100, 385]],
  ["Bộ Kiểm thử, có hiệu lực từ ngày 01 tháng 5 năm 2020, được sửa đổi, bổ sung bởi:", [200, 392, 1100, 417]],
  ["1. Thông tư số 05/2024/TT-BKT ngày 10 tháng 1 năm 2024 của Bộ trưởng", [260, 430, 1100, 455]],
];
const NATIVE_BLOCK = [
  ["BỘ KIỂM THỬ", [80, 190, 320, 203]], ["XÁC THỰC VĂN BẢN HỢP NHẤT", [337, 190, 550, 203]],
  ["Hà Nội, ngày 31 tháng 12 năm 2025", [337, 223, 546, 236]], ["Số: 12 /VBHN-BKT", [128, 223, 280, 236]],
  ["Nơi nhận:", [81, 251, 133, 262]], ["KT. BỘ TRƯỞNG", [387, 253, 497, 267]], ["- Văn phòng Kiểm thử;", [81, 263, 267, 274]],
];
function consolidated({pageOne = PAGE_ONE, block = "native", rows} = {}) {
  const lines = pageOne.map(([text, box], i) => ocrLine(text, box, i + 1));
  const text = lines.map(line => line.text).join("\n");
  const result = {method: "metadata_fast", partial_result: true, source: "header_ocr", used_ocr: true, source_page_count: 40,
    page_count: 1, inspected_pages: [1], processed_pages: [1], line_count: lines.length, text,
    pages: [{page: 1, width: 1224, height: 1584, coordinate_system: "raster_pixels", roi: [0, 0, 1224, 713], lines, text}],
    fast_metadata: {needs_review: true, header_complete: false}};
  if (block) {
    const native = block === "native";
    const blockLines = (rows ?? NATIVE_BLOCK).map(([text, box], i) => native ? nativeLine(text, box, i + 1)
      : ocrLine(text, box.map(value => value * 2), i + 1));
    result.consolidation_block = {page: 15, width: native ? 612 : 1224, height: native ? 792 : 1584,
      coordinate_system: native ? "pdf_points" : "raster_pixels", roi: native ? [0, 174, 612, 269] : [0, 348, 1224, 538],
      lines: blockLines, text: blockLines.map(line => line.text).join("\n"), located_by: native ? "text_layer" : "red_seal",
      read_by: native ? "native_text" : "vietocr_ocr"};
  }
  return result;
}

describe("consolidated text without a page-1 header", () => {
  test("number, date and agency come from the authentication block, for review, with its page", () => {
    const raw = consolidated(), snapshot = JSON.stringify(raw);
    expect(() => validateFastResult(raw)).not.toThrow();
    const draft = createDocumentDraft(raw), values = documentValues(draft);
    expect(values).toMatchObject({arcDocCode: "12/VBHN-BKT", codeNumber: "12", codeNotation: "VBHN-BKT", issuedDate: "31-12-2025",
      organName: "BỘ KIỂM THỬ", typeName: "VBHN", subject: "Quy định về kiểm thử hợp nhất", numberOfPage: "40"});
    for (const key of ["arcDocCode", "issuedDate", "organName", "typeName"]) expect(draft.fields[key].status).toBe("review");
    expect(draft.fields.arcDocCode.note).toContain("khối “XÁC THỰC VĂN BẢN HỢP NHẤT” trang 15 (lớp chữ PDF)");
    expect(draft.fields.arcDocCode.evidence[0]).toMatchObject({page: 15, text: "Số: 12 /VBHN-BKT", coordinateSystem: "pdf_points"});
    expect(draft.fields.organName.evidence.map(source => source.text)).toEqual(["BỘ KIỂM THỬ"]);
    // the title is the consolidated act's, never this text's type
    expect(draft.typeLabel).toBe("Văn bản hợp nhất");
    expect(draft.fields.typeName.note).toContain("“THÔNG TƯ” là của văn bản được hợp nhất");
    expect(partialScope(raw)).toContain("Khối xác thực văn bản hợp nhất: trang 15 (lớp chữ PDF)");
    expect(JSON.stringify(raw)).toBe(snapshot);
  });
  test("a handwritten date read as other characters stays empty for review; its digits are never guessed", () => {
    const rows = NATIVE_BLOCK.map(([text, box]) => [text.startsWith("Hà Nội") ? "Hà Nội, ngày 3/ tháng 1, năm 2025" : text.replace("12 /", "12/"), box]);
    const draft = createDocumentDraft(consolidated({block: "ocr", rows}));
    expect(documentValues(draft)).toMatchObject({arcDocCode: "12/VBHN-BKT", issuedDate: "", organName: "BỘ KIỂM THỬ", typeName: "VBHN"});
    expect(draft.fields.issuedDate.status).toBe("review");
    expect(draft.fields.issuedDate.note).toContain("trang 15 (OCR)");
    expect(draft.fields.issuedDate.note).toContain("không tự sửa hay đoán chữ số");
    expect(draft.fields.issuedDate.evidence[0]).toMatchObject({page: 15, text: "Hà Nội, ngày 3/ tháng 1, năm 2025"});
  });
  test("the block's rows end at the recipients: a recipient is never taken for the agency", () => {
    // the "Số:" row was not read, so no number row bounds the agency column; "Nơi nhận:" still does
    const rows = [...NATIVE_BLOCK.slice(0, 3), ["Nơi nhận:", [81, 236, 133, 246]], ["Bộ Tư pháp;", [81, 247, 160, 257]]];
    const draft = createDocumentDraft(consolidated({rows}));
    expect(documentValues(draft)).toMatchObject({organName: "BỘ KIỂM THỬ", arcDocCode: "", issuedDate: "31-12-2025"});
    expect(draft.fields.arcDocCode.note).toContain("chưa đọc được giá trị này");
  });
  test("a body line ending just above the block, with a date of its own, is not one of its rows", () => {
    // review, 2026-11-10: the block's own date line was not read; the body's date must not take its place
    const rows = [["có hiệu lực thi hành, ngày 01 tháng 7 năm 2025.", [80, 180, 500, 190]],
      ...NATIVE_BLOCK.filter(([text]) => !text.startsWith("Hà Nội"))];
    const draft = createDocumentDraft(consolidated({rows}));
    expect(documentValues(draft)).toMatchObject({issuedDate: "", arcDocCode: "12/VBHN-BKT", organName: "BỘ KIỂM THỬ"});
    expect(draft.fields.issuedDate.note).toContain("chưa đọc được giá trị này");
  });
  test("an agency read on one line with the heading is split from it", () => {
    const rows = [["BỘ KIỂM THỬ XÁC THỰC VĂN BẢN HỢP NHẤT", [80, 190, 550, 203]], ...NATIVE_BLOCK.slice(2)];
    const draft = createDocumentDraft(consolidated({block: "ocr", rows}));
    expect(documentValues(draft)).toMatchObject({organName: "BỘ KIỂM THỬ", arcDocCode: "12/VBHN-BKT", typeName: "VBHN"});
  });
  test("without the block, page 1's closing sentence still marks the type and the agency is left to the reader", () => {
    const draft = createDocumentDraft(consolidated({block: null}));
    expect(documentValues(draft)).toMatchObject({typeName: "VBHN", arcDocCode: "", issuedDate: "", organName: ""});
    expect(draft.fields.typeName.evidence.map(source => source.text)).toContain(PAGE_ONE[5][0]);
    expect(draft.fields.organName.note).toContain("XÁC THỰC VĂN BẢN HỢP NHẤT");
    // OCR can misread a diacritic in the sentence ("sửa đối"); the comparison folds them, the shown text is unchanged
    const misread = PAGE_ONE.map(([text, box]) => [text.replace("sửa đổi", "sửa đối"), box]);
    expect(documentValues(createDocumentDraft(consolidated({pageOne: misread, block: null}))).typeName).toBe("VBHN");
  });
  test("a page-1 header of its own is kept, and the block does not replace it", () => {
    const pageOne = [["BỘ TRANG MỘT", [90, 100, 330, 125]], ["Số: 7/2026/VBHN-BTM", [90, 140, 330, 165]], ...PAGE_ONE];
    const values = documentValues(createDocumentDraft(consolidated({pageOne})));
    expect(values).toMatchObject({organName: "BỘ TRANG MỘT", arcDocCode: "7/2026/VBHN-BTM", issuedDate: "", typeName: "VBHN"});
  });
  test("a page-1 number without its agency is a header of its own: the block does not replace it", () => {
    const pageOne = [["Số: 7/2020/TT-BKT", [90, 140, 330, 165]], ...PAGE_ONE];
    const draft = createDocumentDraft(consolidated({pageOne}));
    expect(documentValues(draft)).toMatchObject({arcDocCode: "7/2020/TT-BKT", organName: "", issuedDate: "", typeName: "TT"});
  });
  test("an old-layout consolidated text keeps its agency note when the block is not used", () => {
    // its own "Số: …/VBHN-…" on page 1, an agency name outside the known issuers, and a block further on
    const pageOne = [["NGÂN HÀNG KIỂM THỬ", [90, 100, 330, 125]], ["Số: 7/VBHN-NHKT", [90, 140, 330, 165]], ...PAGE_ONE];
    const draft = createDocumentDraft(consolidated({pageOne}));
    expect(documentValues(draft)).toMatchObject({arcDocCode: "7/VBHN-NHKT", organName: "", typeName: "VBHN"});
    expect(draft.fields.organName.status).toBe("review");
    expect(draft.fields.organName.note).toContain("nhập tay");
  });
  test("the sentence counts only between the title and the body: a legal basis citing an amended law does not", () => {
    const basis = [...PAGE_ONE.slice(0, 4), ["Căn cứ Luật Kiểm thử được sửa đổi, bổ sung bởi Luật số 9/2024/QH15;", [200, 360, 1100, 385]]];
    const draft = createDocumentDraft(consolidated({pageOne: basis, block: null}));
    expect(documentValues(draft).typeName).toBe("TT");
  });
  test("a full-text mode finds the block among its pages too, and its values stay for review", () => {
    const page = (number, rows) => ({page: number, width: 612, height: 792,
      lines: rows.map(([text, box], i) => nativeLine(text, box, i + 1))});
    const pageOne = PAGE_ONE.map(([text, box]) => [text, box.map(value => value / 2)]);
    const raw = {method: "native_text", page_count: 3, pages: [page(1, pageOne), page(2, [["Điều 2. Nội dung kiểm thử.", [80, 60, 500, 75]]]),
      page(3, NATIVE_BLOCK)]};
    const draft = createDocumentDraft(raw);
    expect(documentValues(draft)).toMatchObject({arcDocCode: "12/VBHN-BKT", issuedDate: "31-12-2025", organName: "BỘ KIỂM THỬ", typeName: "VBHN"});
    for (const key of ["arcDocCode", "issuedDate", "organName"]) expect(draft.fields[key].status).toBe("review");
    expect(draft.fields.issuedDate.note).toContain("trang 3 (lớp chữ PDF)");
  });
  test("a malformed block is refused like any malformed fast result", () => {
    const cases = {
      "page 1": raw => {raw.consolidation_block.page = 1;},
      "beyond the source": raw => {raw.consolidation_block.page = 41;},
      "geometry": raw => {raw.consolidation_block.lines[0].geometry_source = "vietocr_ocr";},
      "coordinates": raw => {raw.consolidation_block.coordinate_system = "raster_pixels";},
      "line numbers": raw => {raw.consolidation_block.lines[1].line_index = 5;},
      "text": raw => {raw.consolidation_block.text = "khác";},
      "empty": raw => {raw.consolidation_block.lines = []; raw.consolidation_block.text = "";},
      "source": raw => {raw.consolidation_block.located_by = "guess";},
      "no box": raw => {delete raw.consolidation_block.lines[0].bbox;},
      "short box": raw => {raw.consolidation_block.lines[0].bbox = [1, 2, 3];},
    };
    for (const [name, spoil] of Object.entries(cases)) {
      const raw = consolidated(); spoil(raw);
      expect(() => validateFastResult(raw), name).toThrow();
    }
    const scan = consolidated({block: "ocr"});
    expect(() => validateFastResult(scan)).not.toThrow();
    delete scan.consolidation_block.lines[0].polygon;
    expect(() => validateFastResult(scan), "no polygon").toThrow();
  });
});

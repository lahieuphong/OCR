// Entirely synthetic text/geometry, created for these tests. No real document or labels.
export function syntheticDocument({method = "native_text", kind = "CÔNG VĂN", code = "00103/TEST-CN", date = "08 tháng 10 năm 2026", extra = [], pages = 1} = {}) {
  const rows = [
    ["VĂN PHÒNG KIỂM THỬ", 45, 35, 270, 50],
    ["CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", 320, 35, 570, 50],
    ["Độc lập - Tự do - Hạnh phúc", 350, 60, 560, 75],
    ...(code == null ? [] : [[`Số: ${code}`, 45, 95, 260, 110]]),
    [`Hà Nội, ngày ${date}`, 320, 95, 570, 110],
    [kind, 175, 140, 420, 158],
    ["V/v kiểm thử trích xuất thông tin", 130, 175, 460, 190],
    ["trên tài liệu tổng hợp, giữ nguyên tiếng Việt", 130, 198, 460, 213],
    ...extra,
    ["Căn cứ Quyết định số 999/QĐ-BODY ngày 01 tháng 01 năm 2020;", 45, 260, 555, 277],
    ["Điều 1. Nội dung giả lập, không phải hồ sơ thực tế.", 45, 290, 555, 308],
  ];
  return documentFromRows(rows, {method, pages});
}
export function documentFromRows(rows, {method = "native_text", pages = 1} = {}) {
  const scale = method === "native_text" ? 1 : 2;
  const allPages = Array.from({length: pages}, (_, p) => {
    const lines = (p ? [[`Trang tổng hợp ${p + 1}`, 45, 50, 300, 65]] : rows).map(([text, x0, y0, x1, y1], i) => ({
      text, line_index: i + 1, ...(method === "native_text"
        ? {bbox: [x0, y0, x1, y1], block_index: i}
        : {polygon: [[x0, y0], [x1, y0], [x1, y1], [x0, y1]].map(pt => pt.map(n => n * scale)), hit_decoder_limit: false}),
    }));
    return {page: p + 1, width: 595 * scale, height: 842 * scale, lines, text: lines.map(line => line.text).join("\n")};
  });
  return {method, source: method === "native_text" ? "embedded_pdf_text_layer" : "ocr_from_rendered_pages",
    used_ocr: method === "vietocr_ocr", page_count: pages, pages: allPages, text: allPages.map(p => p.text).join("\n\n"),
    line_count: allPages.reduce((n, p) => n + p.lines.length, 0), elapsed_ms: 250};
}
export const SYNTHETIC_CASES = {
  officialLetter: syntheticDocument(), decision: syntheticDocument({kind: "QUYẾT ĐỊNH", code: "00002/QĐ-TEST"}),
  resolution: syntheticDocument({kind: "NGHỊ QUYẾT", code: "00321/NQ-TEST"}),
  ambiguousCode: syntheticDocument({code: "1O3?0/TEST-CN"}),
  competingDates: syntheticDocument({extra: [["Hà Nội, ngày 09 tháng 10 năm 2026", 320, 120, 570, 135]]}),
  noCode: syntheticDocument({code: null}), unreadableScan: documentFromRows([], {method: "vietocr_ocr"}),
  twoColumnHeader: syntheticDocument({method:"vietocr_ocr"}),
  bodyReferences: syntheticDocument({code:null,extra:[["Văn bản dẫn chiếu: Số 555/REF-A; số 777/REF-B.",45,500,555,515]]}),
  wrappedCode: documentFromRows([["VĂN PHÒNG KIỂM THỬ",45,35,270,50],["Số:",45,95,120,110],["00103/TEST-CN",45,115,260,130],["CÔNG VĂN",175,150,420,168],["V/v kiểm tra dòng số xuống dòng",130,180,460,195]]),
};

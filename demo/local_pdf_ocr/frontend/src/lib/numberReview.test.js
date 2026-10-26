import {describe, expect, test} from "vitest";
import {findNumberReviewCandidates, findNumberReviewTargets} from "./numberReview.js";

const line = (line_index, text, x, y, w = 270, h = 31) => ({line_index, text,
  polygon: [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]});
function document(text = "Số: 4H7/TEST", extra = []) {
  return {method: "vietocr_ocr", used_ocr: true, text: "Original OCR is retained",
    pages: [{page: 1, width: 1192, height: 1686, lines: [
      line(1, "BỘ KIỂM THỬ", 210, 130), line(2, text, 210, 233),
      line(3, "Hà Nội, ngày 12 tháng 3 năm 2025", 650, 235, 400), ...extra]}]};
}

describe("number review hints", () => {
  test.each([["Số: 4H7/TEST", "non_digit_serial"], ["Số: 3 7/TEST", "split_digits"],
    ["Số: /TEST", "empty_serial"], ["Số: 147", "incomplete_code"], ["So: 147/TEST", "uncertain_prefix"],
    ["Số: 4?7/TEST", "non_digit_serial"], ["Số: Ô47/TEST", "non_digit_serial"]])("flags %s without proposing a replacement", (text, reason) => {
    const raw = document(text), before = JSON.stringify(raw);
    const found = findNumberReviewCandidates(raw);
    expect(found).toHaveLength(1); expect(found[0].reasons).toContain(reason);
    expect(found[0].text).toBe(text); expect(found[0].replacement_text).toBeUndefined();
    expect(JSON.stringify(raw)).toBe(before);
  });
  test.each(["Số: 147/TEST", "Số: 00147 /2026/TEST", "Số：147/TEST", "Số 147/TEST"])("allows image review of an apparently valid %s without a warning", text => {
    expect(findNumberReviewCandidates(document(text))).toEqual([]);
    expect(findNumberReviewTargets(document(text))).toHaveLength(1);
  });
  test("missing prefix requires serial shape and a separate aligned dateline", () => {
    const raw = document("5ô: 4H7/TEST");
    expect(findNumberReviewCandidates(raw)[0]).toMatchObject({line_index: 2, reasons: ["geometry_possible_number"]});
    raw.pages[0].lines = raw.pages[0].lines.filter(row => row.line_index !== 3);
    expect(findNumberReviewCandidates(raw)[0]).toMatchObject({polygon: null, reasons: ["number_field_not_located"]});
  });
  test.each(["BỘ KIỂM THỬ", "V/v thực hiện Đề án 2026", "V/v 2026 triển khai", "THÔNG TƯ VỀ CHI PHÍ"])("does not crop unrelated date-adjacent header %s", text => {
    const candidates = findNumberReviewCandidates(document(text));
    expect(candidates).toHaveLength(1); expect(candidates[0].polygon).toBeNull();
  });
  test("only page-one header rows count, and explicit rows suppress geometry fallback", () => {
    const raw = document("Số: 147/TEST", [line(4, "4H7/OTHER", 210, 236),
      line(5, "Căn cứ số 7/REFERENCE", 210, 650), line(6, "Số: RU8/BODY", 210, 680)]);
    raw.pages.push({page: 2, width: 1192, height: 1686, lines: [line(1, "Số: 4H7/SECOND", 210, 233)]});
    expect(findNumberReviewCandidates(raw)).toEqual([]);
    expect(findNumberReviewTargets(raw).map(item => item.text)).toEqual(["Số: 147/TEST"]);
  });
  test("a title or body marker excludes a later number-shaped row even near the top", () => {
    for (const marker of ["QUYẾT ĐỊNH", "CÔNG VĂN", "THÔNG BÁO:", "Căn cứ Quyết định", "Về việc kiểm thử"]) {
      const raw = document("Số: RU8/REFERENCE", [line(4, marker, 200, 200)]);
      expect(findNumberReviewCandidates(raw)[0].polygon).toBeNull();
    }
  });
  test("H1 retains raster review; native text never produces OCR crop coordinates", () => {
    expect(findNumberReviewCandidates({...document(), method: "hybrid_h1"})).toHaveLength(1);
    for (const value of [null, {...document(), method: "native_text"}, {...document(), used_ocr: false}]) {
      expect(findNumberReviewTargets(value)).toEqual([]);
    }
  });
  test("invalid, crossed or out-of-page polygons cannot be sent as crop targets", () => {
    for (const polygon of [null, [[NaN, 233], [480, 233], [480, 264], [210, 264]],
      [[210, 233], [480, 264], [480, 233], [210, 264]],
      [[-1, 233], [480, 233], [480, 264], [-1, 264]]]) {
      const raw = document(); raw.pages[0].lines[1].polygon = polygon;
      expect(findNumberReviewCandidates(raw)[0].polygon).toBeNull();
    }
  });
  test("returned geometry is copied so review code cannot mutate OCR result polygons", () => {
    const raw = document(), before = JSON.stringify(raw);
    const selected = findNumberReviewTargets(raw)[0]; selected.polygon[0][0] = 0;
    expect(JSON.stringify(raw)).toBe(before);
  });
});

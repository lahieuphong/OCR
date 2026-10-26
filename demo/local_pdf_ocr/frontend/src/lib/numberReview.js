/** Read-only hints from page-one OCR geometry. No character replacements. */
const OCR_METHODS = new Set(["vietocr_ocr", "hybrid_h1"]);
const PREFIX = /^\s*s[ốo]\s*(?:[:：﹕.\-]\s*|\s+|$)/iu;
const DATE = /ngày\s*\d{1,2}\s+tháng\s*\d{1,2}/iu;
const HEADER_END = /^(?:Căn cứ(?=\s|$|[:,])|Kính gửi(?=\s|$|[:,])|Điều\s+\d|(?:QUYẾT ĐỊNH|NGHỊ QUYẾT|CÔNG VĂN|THÔNG BÁO|BÁO CÁO|KẾ HOẠCH|TỜ TRÌNH)(?:\s*:)?$|QUYẾT NGHỊ\s*:|Nơi nhận\s*:|V\/v(?=\s|$)|Về việc(?=\s|$))/iu;

export const NUMBER_REVIEW_REASONS = {
  non_digit_serial: "Phần số trước dấu / có ký tự không phải chữ số.",
  split_digits: "Có khoảng trắng nằm giữa các chữ số.",
  empty_serial: "Chưa đọc được phần số văn bản.",
  incomplete_code: "Chưa đọc đủ dấu / và ký hiệu văn bản.",
  uncertain_prefix: "Tiền tố Số có ký tự cần đối chiếu.",
  geometry_possible_number: "Dòng nằm cùng hàng với ngày ban hành nhưng chưa đọc rõ tiền tố Số.",
  number_field_not_located: "Chưa định vị được dòng số/ký hiệu; cần xem toàn bộ trang 1.",
};

function bounds(line) {
  const points = line?.polygon;
  if (!Array.isArray(points) || points.length !== 4
      || !points.every(p => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite))) return null;
  // A crossed or degenerate quadrilateral cannot identify a crop reliably.
  const turns = points.map((a, i) => {
    const b = points[(i + 1) % 4], c = points[(i + 2) % 4];
    return (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]);
  });
  if (!turns.every(n => n > 0) && !turns.every(n => n < 0)) return null;
  const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
  return {x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys),
    yc: (Math.min(...ys) + Math.max(...ys)) / 2};
}

function serialFlags(value) {
  const text = String(value ?? ""), prefix = PREFIX.exec(text);
  if (!prefix) return [];
  const tail = text.slice(prefix[0].length), serial = tail.split("/", 1)[0].trim();
  const reasons = [];
  if (!/^\s*Số/iu.test(prefix[0])) reasons.push("uncertain_prefix");
  if (!serial) reasons.push("empty_serial");
  else {
    if (/\d\s+\d/u.test(serial)) reasons.push("split_digits");
    if (/[^0-9\s]/u.test(serial)) reasons.push("non_digit_serial");
  }
  if (!tail.includes("/") || !tail.slice(tail.indexOf("/") + 1).trim()) reasons.push("incomplete_code");
  return reasons;
}

function target(line, page, reasons, index) {
  return {page: 1, line_index: Number.isInteger(line.line_index) && line.line_index > 0 ? line.line_index : null,
    text: String(line.text ?? ""), polygon: line.polygon.map(p => [...p]),
    width: page.width, height: page.height, reasons, review_key: `p1_${index}`};
}

/** Includes located, apparently valid rows so a user can still inspect their image. */
export function findNumberReviewTargets(result) {
  if (!OCR_METHODS.has(result?.method) || result?.used_ocr !== true || !Array.isArray(result.pages)) return [];
  const page = result.pages.find(p => p?.page === 1);
  if (!page || !Number.isInteger(page.width) || !Number.isInteger(page.height)
      || page.width <= 0 || page.height <= 0 || !Array.isArray(page.lines)) return [];
  const {width: W, height: H} = page;
  const located = page.lines.map((line, index) => ({line, index, box: bounds(line)}))
    .filter(item => item.box && item.box.x0 >= 0 && item.box.y0 >= 0 && item.box.x1 <= W && item.box.y1 <= H);
  const headerEnd = Math.min(.37 * H, ...located.filter(item => HEADER_END.test(String(item.line.text ?? "").trim()))
    .map(item => item.box.y0));
  const header = located.filter(({box}) => box.x0 < .60 * W && box.y0 > .045 * H
    && box.y0 < headerEnd && box.y1 - box.y0 < .08 * H);
  const explicit = header.filter(({line}) => PREFIX.test(String(line.text ?? "")));
  if (explicit.length) return explicit.map(({line, index}) => target(line, page, serialFlags(line.text), index));

  const dates = located.filter(({line, box}) => box.x0 > .40 * W && box.y0 < .38 * H && DATE.test(String(line.text ?? "")));
  const aligned = header.filter(({line, box}) => {
    const text = String(line.text ?? ""), slash = text.indexOf("/"), serial = text.slice(0, slash);
    return slash > 0 && slash <= 24 && /[0-9]/u.test(serial)
      && !HEADER_END.test(text.trim())
      && dates.some(({box: date}) => box.x1 < date.x0 && Math.abs(box.yc - date.yc) < .024 * H);
  });
  if (aligned.length) return aligned.map(({line, index}) => target(line, page, ["geometry_possible_number"], index));
  return [{page: 1, line_index: null, text: "", polygon: null, width: W, height: H,
    reasons: ["number_field_not_located"], review_key: "p1_unlocated"}];
}

export function findNumberReviewCandidates(result) {
  return findNumberReviewTargets(result).filter(item => item.reasons.length > 0);
}

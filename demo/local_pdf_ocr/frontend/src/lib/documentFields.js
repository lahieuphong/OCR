// Business codes supplied by the project brief. No unverified document-type codes.
export const CATALOGS = {
  maintenance: {"01": "Vĩnh viễn", "02": "75 năm", "03": "50 năm", "04": "30 năm", "05": "20 năm", "06": "10 năm", "07": "5 năm"},
  typeName: {"01": "Nghị quyết", "02": "Quyết định", "22": "Công văn"},
  language: {"01": "Tiếng Việt", "02": "Tiếng Anh"},
  mode: {"01": "Công khai", "02": "Có điều kiện", "03": "Mật"},
  format: {"01": "Tốt", "02": "Bình thường", "03": "Hỏng"},
  process: {"0": "Không", "1": "Có"}, riskRecovery: {"0": "Không", "1": "Có"},
  riskRecoveryStatus: {"01": "Đã dự phòng", "02": "Chưa dự phòng"},
  isCan: {"0": "Đỏ", "1": "Màu khác"},
};
export const FIELD_LABELS = {
  docId: "Mã tài liệu", arcDocCode: "Mã văn bản", maintenance: "Thời hạn lưu trữ", typeName: "Loại tài liệu",
  codeNumber: "Số tài liệu", codeNotation: "Ký hiệu văn bản", issuedDate: "Ngày ban hành", organName: "Cơ quan ban hành",
  subject: "Trích yếu nội dung", language: "Ngôn ngữ", numberOfPage: "Số trang", inforSign: "Ký hiệu thông tin",
  keyword: "Từ khóa", mode: "Chế độ sử dụng", confidenceLevel: "Mức độ tin cậy", autograph: "Bút tích",
  format: "Tình trạng vật lý", process: "Quy trình xử lý", riskRecovery: "Chế độ dự phòng",
  riskRecoveryStatus: "Tình trạng dự phòng", description: "Ghi chú", isCan: "Màu con dấu",
};
export const FIELD_KEYS = Object.freeze(Object.keys(FIELD_LABELS));
export const FIELD_GROUPS = [
  {title: "Thông tin văn bản", keys: ["docId", "arcDocCode", "codeNumber", "codeNotation", "typeName", "issuedDate", "organName", "subject", "language", "numberOfPage"]},
  {title: "Lưu trữ và quản lý", keys: ["maintenance", "inforSign", "keyword", "mode", "confidenceLevel", "autograph"]},
  {title: "Tình trạng và xử lý", keys: ["format", "process", "riskRecovery", "riskRecoveryStatus", "isCan", "description"]},
];
export const READ_ONLY = new Set(["docId", "codeNumber", "codeNotation", "numberOfPage", "confidenceLevel"]);
export const STATUS_LABELS = {recognized: "Đã nhận diện", review: "Cần kiểm tra", confirmed: "Đã xác nhận", unknown: "Chưa xác định"};

const clean = text => String(text ?? "").normalize("NFC").trim().replace(/\s+/gu, " ");
const bodyStart = /^(?:Căn cứ(?=\s|$|[:,])|Kính gửi(?=\s|$|[:,])|Điều\s+\d|QUYẾT ĐỊNH\s*:|QUYẾT NGHỊ\s*:|Nơi nhận\s*:|KT\.|TM\.)/iu;
const national = /CỘNG HÒA|XÃ HỘI CHỦ NGHĨA|Độc lập\s*[-–—]|Tự do\s*[-–—]|Hạnh phúc/iu;
const issuer = /^(?:VĂN PHÒNG|ỦY BAN|HỘI ĐỒNG|BỘ\s|SỞ\s|PHÒNG\s|CỤC\s|TỔNG CỤC|CHÍNH PHỦ$|THỦ TƯỚNG CHÍNH PHỦ$|QUỐC HỘI$|TÒA ÁN|VIỆN KIỂM SÁT|CƠ QUAN\s)/iu;
const title = /^(NGHỊ QUYẾT|QUYẾT ĐỊNH|CÔNG VĂN|THÔNG BÁO|BÁO CÁO|KẾ HOẠCH|TỜ TRÌNH)$/iu;
const typeCodes = {"NGHỊ QUYẾT": "01", "QUYẾT ĐỊNH": "02", "CÔNG VĂN": "22"};
const numberLabel = /^Số\s*(?:[:：﹕]\s*)?(.*)$/iu;
const subjectLabel = /^(?:V\/v\s*[:：]?|Về việc\s*[:：]?)\s*(.*)$/iu;
const codePattern = /^[\p{L}\p{N}\p{Pd}._?\uFFFD]+(?:\s*\/\s*[\p{L}\p{N}\p{Pd}._?\uFFFD]+)+/u;

function bounds(line, method) {
  if (method === "native_text" && Array.isArray(line.bbox) && line.bbox.length === 4 && line.bbox.every(Number.isFinite)) return [...line.bbox];
  if (["vietocr_ocr", "hybrid_h1"].includes(method) && Array.isArray(line.polygon) && line.polygon.length === 4
    && line.polygon.every(p => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite))) {
    const xs = line.polygon.map(p => p[0]), ys = line.polygon.map(p => p[1]);
    return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
  }
  return null;
}

// Coordinates are interpreted only within their own page and their own method.
// Native line bboxes describe whole blocks; they are never advertised as exact line highlights.
function readLines(result) {
  const pages = Array.isArray(result?.pages) ? [...result.pages].sort((a, b) => a.page - b.page) : [];
  return pages.flatMap((page, p) => {
    const lines = Array.isArray(page.lines) && page.lines.length ? page.lines
      : String(page.text ?? (pages.length === 1 ? result.text ?? "" : "")).split(/\r?\n/u).map((text, i) => ({text, line_index: i + 1}));
    return lines.map((line, i) => {
      const box = bounds(line, result.method);
      const spatial = box && page.width > 0 && page.height > 0 && box[2] > box[0] && box[3] > box[1];
      return {text: String(line.text ?? ""), match: clean(line.text), page: page.page ?? p + 1,
        line: line.line_index ?? i + 1, order: i, block: line.block_index,
        box: spatial ? box : null, x: spatial ? (box[0] + box[2]) / (2 * page.width) : null,
        y: spatial ? box[1] / page.height : null,
        coordinateSystem: result.method === "native_text" ? "pdf_points" : "raster_pixels",
        precision: result.method === "native_text" ? "block" : "polygon"};
    }).filter(line => line.match);
  });
}
function evidence(lines) {
  return lines.map(line => ({page: line.page, line: line.line, text: line.text,
    ...(line.box ? {bounds: [...line.box], coordinateSystem: line.coordinateSystem, precision: line.precision} : {})}));
}
function field(value = "", status = "unknown", sources = [], note = "") {
  return {value, status, evidence: evidence(sources), note};
}
function sameColumn(a, b) {
  if (!a.box || !b.box) return true;
  if (a.block != null && a.block === b.block) return true;
  // Do not combine the left agency/number column with the right national/date column.
  return Math.abs(a.x - b.x) < .27;
}
function successors(line, lines, count = 5) {
  return lines.filter(next => next.order > line.order && sameColumn(line, next)
    && (line.y == null || next.y == null || (next.y >= line.y - .005 && next.y - line.y < .13)))
    .sort((a, b) => a.order - b.order).slice(0, count);
}
function boundary(line) {
  return bodyStart.test(line.match) || national.test(line.match) || numberLabel.test(line.match)
    || /ngày\s+\d/iu.test(line.match) || title.test(line.match) || issuer.test(line.match);
}
function uniqueCandidates(candidates) {
  return [...new Map(candidates.map(c => [c.value, c])).values()];
}
function choose(candidates, message) {
  const unique = uniqueCandidates(candidates);
  if (unique.length === 1) return field(unique[0].value, unique[0].review ? "review" : "recognized", unique[0].lines, unique[0].note || "");
  return unique.length ? field("", "review", unique.flatMap(c => c.lines), message) : field();
}
export function splitDocumentCode(code) {
  const value = String(code ?? "").trim();
  const slash = value.indexOf("/");
  return {codeNumber: slash < 0 ? value : value.slice(0, slash).trim(),
    codeNotation: slash < 0 ? "" : value.slice(value.lastIndexOf("/") + 1).trim()};
}
export function isValidIssuedDate(value) {
  const match = /^(\d{2})-(\d{2})-(\d{4})$/u.exec(value);
  if (!match) return false;
  const [, d, m, y] = match.map(Number);
  if (y < 1000) return false;
  const date = new Date(Date.UTC(y, m - 1, d));
  return date.getUTCFullYear() === y && date.getUTCMonth() === m - 1 && date.getUTCDate() === d;
}

export function createDocumentDraft(result, {sourceKind = "pdf"} = {}) {
  const fields = Object.fromEntries(FIELD_KEYS.map(key => [key, field()]));
  fields.docId.note = "Luôn để trống theo schema nghiệp vụ; không tự sinh mã.";
  const lines = readLines(result);
  const first = lines.filter(line => line.page === 1);
  const textualEnd = first.findIndex(line => bodyStart.test(line.match));
  const bodyY = first.filter(line => bodyStart.test(line.match) && line.y != null).map(line => line.y);
  const header = first.filter((line, i) => line.y != null
    ? line.y < Math.min(.44, ...bodyY) : i < (textualEnd < 0 ? 24 : textualEnd));
  const headingLines = header.filter(line => title.test(line.match) || subjectLabel.test(line.match));
  const headingY = Math.min(...headingLines.map(line => line.y ?? Infinity));
  const headingOrder = Math.min(...headingLines.map(line => line.order));
  const identityHeader = header.filter(line => line.y != null && headingY !== Infinity ? line.y < headingY : line.order < headingOrder);
  const codes = [];
  let incompleteCode = false;
  for (const line of identityHeader) {
    const label = numberLabel.exec(line.match);
    if (!label) continue;
    let candidate = label[1], used = [line];
    for (const next of successors(line, identityHeader, 3)) {
      if (codePattern.test(candidate) && !candidate.trim().endsWith("/")) break;
      if (boundary(next)) break;
      candidate += " " + next.match;
      used.push(next);
    }
    const matched = codePattern.exec(candidate.trim());
    if (matched) {
      if (candidate.trim().slice(matched[0].length).trim()) {
        incompleteCode = true;
        fields.arcDocCode = field("", "review", used, "Dòng số/ký hiệu có đoạn chưa phân tách rõ; cần kiểm tra nguyên bản.");
        continue;
      }
      const value = matched[0].replace(/\s*\/\s*/gu, "/").trim();
      const review = !/^\d+\//u.test(value) || /[?\uFFFD]/u.test(value) || used.some(x => /\|/u.test(x.match));
      codes.push({value, lines: used, review, note: review ? "Có ký tự OCR chưa chắc chắn; đối chiếu bản gốc. Không tự thay ký tự." : ""});
    } else {incompleteCode = true; fields.arcDocCode = field("", "review", used, "Dòng Số chưa có số/ký hiệu đầy đủ; cần đối chiếu bản gốc.");}
  }
  if (codes.length) fields.arcDocCode = incompleteCode
    ? field("", "review", identityHeader.filter(line => numberLabel.test(line.match)), "Có dòng số/ký hiệu chưa đầy đủ cạnh tranh với ứng viên khác; cần kiểm tra.")
    : choose(codes, "Có nhiều số/ký hiệu cạnh tranh trong header; chưa chọn tự động.");
  if (fields.arcDocCode.value) {
    for (const [key, value] of Object.entries(splitDocumentCode(fields.arcDocCode.value))) fields[key] = {...fields.arcDocCode, value};
  }

  const dates = [];
  for (const line of identityHeader) {
    const used = [line];
    let text = line.match;
    if (/ngày\s+\d/iu.test(text) && !/năm\s+\d{4}/iu.test(text)) {
      for (const next of successors(line, identityHeader, 2)) {
        if (!/^(?:tháng|năm|\d)/iu.test(next.match)) break;
        text += " " + next.match; used.push(next);
      }
    }
    const regex = /^(?:[\p{L}\s.]{1,70},\s*)?ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})/giu;
    for (const match of text.matchAll(regex)) {
      const value = `${match[1].padStart(2, "0")}-${match[2].padStart(2, "0")}-${match[3]}`;
      dates.push({value, lines: used, invalid: !isValidIssuedDate(value) || Boolean(text.slice(match[0].length).replace(/[.\s]/gu, ""))});
    }
  }
  if (dates.some(date => date.invalid)) fields.issuedDate = field("", "review", dates.flatMap(c => c.lines), "Ngày trong header không hợp lệ hoặc cạnh tranh; không tự sửa ngày/tháng.");
  else fields.issuedDate = choose(dates, "Có nhiều ngày ban hành cạnh tranh trong header; cần xác nhận.");

  const firstCodeY = Math.min(...header.filter(line => numberLabel.test(line.match)).map(line => line.y ?? Infinity));
  const agencies = identityHeader.filter(line => issuer.test(line.match) && !national.test(line.match)
    && (line.y == null || line.y < firstCodeY) && (line.x == null || line.x < .52));
  const agencyCandidates = agencies.map(line => {
    const used = [line];
    for (const next of successors(line, header, 2)) {
      if (boundary(next) || next.match !== next.match.toLocaleUpperCase("vi") || !/\p{L}/u.test(next.match)
        || (line.y != null && next.y - line.y > .065)) break;
      used.push(next);
    }
    return {value: used.map(x => x.match).join(" ").toLocaleUpperCase("vi"), lines: used};
  });
  fields.organName = choose(agencyCandidates, "Header có nhiều cơ quan/cấp cơ quan; chưa xác định cơ quan ban hành.");

  const titles = header.filter(line => title.test(line.match));
  const classified = titles.map(line => ({value: typeCodes[line.match.toLocaleUpperCase("vi")], lines: [line]})).filter(c => c.value);
  fields.typeName = choose(classified, "Có nhiều loại văn bản cạnh tranh; cần kiểm tra.");
  if (new Set(titles.map(line => line.match.toLocaleUpperCase("vi"))).size > 1) fields.typeName = field("", "review", titles, "Có nhiều tiêu đề loại văn bản cạnh tranh; cần xác nhận.");
  if (!classified.length && titles.length) fields.typeName = field("", "review", titles, "Loại tài liệu chưa có mã nghiệp vụ được xác minh trong danh mục.");
  const subjects = [];
  const explicit = header.filter(line => subjectLabel.test(line.match));
  const anchors = explicit.length ? explicit : titles;
  for (const line of anchors) {
    const tail = subjectLabel.exec(line.match)?.[1] ?? "";
    const used = [line], parts = tail ? [tail] : [];
    for (const next of successors(line, header, 5)) {
      if (boundary(next) || subjectLabel.test(next.match)) break;
      const previous = used.at(-1);
      if (next.y != null && previous.y != null && next.y - previous.y > .045) break;
      parts.push(next.match); used.push(next);
    }
    if (parts.length) subjects.push({value: parts.join(" "), lines: used,
      review: parts.length >= 5, note: parts.length >= 5 ? "Tiêu đề dài; kiểm tra điểm kết thúc trích yếu." : ""});
  }
  fields.subject = choose(subjects, "Có nhiều trích yếu cạnh tranh; chưa ghép tự động.");

  const vi = lines.filter(line => national.test(line.match) || /\b(?:ngày|tháng|năm|việc|văn bản|quyết định|nghị quyết)\b/iu.test(line.match));
  const en = lines.filter(line => /\b(?:REPUBLIC|GOVERNMENT|DECISION|RESOLUTION)\b/u.test(line.match) || /\b(?:the|and|of|for)\b/giu.test(line.match) && /\b(?:document|issued|administrative|decision)\b/iu.test(line.match));
  if (vi.length && en.length) fields.language = field("", "review", [vi[0], en[0]], "Có bằng chứng nhiều ngôn ngữ; cần xác nhận.");
  else if (vi.length >= 2 || vi.some(line => national.test(line.match))) fields.language = field("01", "recognized", vi.slice(0, 2));
  else if (en.length >= 2) fields.language = field("02", "recognized", en.slice(0, 2));

  const count = sourceKind === "image" ? 1 : result?.page_count;
  if (Number.isInteger(count) && count >= 1 && count <= 6 && Array.isArray(result?.pages) && result.pages.length === count) {
    fields.numberOfPage = {...field(String(count), "recognized"), evidence: [{text: sourceKind === "image" ? "Ảnh nguồn: 1 trang." : `Bộ đọc PDF nguồn trả về page_count = ${count}.`, source: "source_page_count"}]};
  }
  fields.confidenceLevel = {...field("02", "review"), note: "Mã nghiệp vụ, không phải độ chính xác OCR. isCan chưa xác định vẫn thuộc trường hợp khác → 02.", evidence: [{source: "business_rule", text: 'isCan = "0" → 01; các trường hợp khác → 02.'}]};
  // Literal OCR evidence proves the extraction source, not the correctness of its characters.
  // There is no calibrated recognizer confidence: require visual review for all OCR-derived text.
  if (["vietocr_ocr", "hybrid_h1"].includes(result?.method)) {
    for (const entry of Object.values(fields)) if (entry.value && entry.status === "recognized" && entry.evidence.some(source => source.page)) {
      entry.status = "review";
      entry.note = [entry.note, "Nguồn OCR: đối chiếu bản gốc trước khi xác nhận; không tự sửa chữ hoặc dấu."].filter(Boolean).join(" ");
    }
  }
  return {fields, dirty: false, method: result?.method ?? ""};
}

export function editDocumentField(draft, key, value) {
  if (!FIELD_KEYS.includes(key) || READ_ONLY.has(key)) return draft;
  const fields = {...draft.fields, [key]: {...draft.fields[key], value: String(value), status: value ? "confirmed" : "unknown", note: "Đã chỉnh sửa thủ công; nguồn tự động chỉ để đối chiếu."}};
  if (key === "organName") fields[key].value = fields[key].value.toLocaleUpperCase("vi");
  if (key === "arcDocCode") {
    for (const [name, part] of Object.entries(splitDocumentCode(value))) fields[name] = {...fields[key], value: value ? part : ""};
  }
  if (key === "isCan") fields.confidenceLevel = {...fields.confidenceLevel, value: value === "0" ? "01" : "02", status: value ? "confirmed" : "review",
    note: value ? "Tính theo màu con dấu đã được người dùng xác nhận; không phải xác suất OCR." : "Chưa xác định màu con dấu; mã nghiệp vụ tạm là 02."};
  return {...draft, fields, dirty: true};
}
export function confirmDocumentField(draft, key) {
  if (!draft.fields[key]?.value || READ_ONLY.has(key)) return draft;
  const fields = {...draft.fields, [key]: {...draft.fields[key], status: "confirmed", note: "Đã được người dùng kiểm tra và xác nhận."}};
  if (key === "arcDocCode") {
    for (const [name, value] of Object.entries(splitDocumentCode(fields.arcDocCode.value))) fields[name] = {...fields[name], value, status:"confirmed", note:"Tính từ mã văn bản đã được người dùng xác nhận."};
  }
  return {...draft, dirty: true, fields};
}
export function documentValues(draft) {
  const values = Object.fromEntries(FIELD_KEYS.map(key => [key, String(draft.fields[key]?.value ?? "")]));
  values.docId = "";
  Object.assign(values, values.arcDocCode ? splitDocumentCode(values.arcDocCode) : {codeNumber: "", codeNotation: ""});
  values.confidenceLevel = values.isCan === "0" ? "01" : "02";
  return values;
}
export function validateDocumentDraft(draft) {
  const values = documentValues(draft), errors = {};
  if (values.arcDocCode && codePattern.exec(values.arcDocCode)?.[0] !== values.arcDocCode) errors.arcDocCode = "Nhập đầy đủ số/ký hiệu, ngăn cách bằng dấu /; không tự sửa ký tự OCR.";
  if (values.issuedDate && !isValidIssuedDate(values.issuedDate)) errors.issuedDate = "Ngày phải hợp lệ, theo DD-MM-YYYY.";
  for (const [key, catalog] of Object.entries(CATALOGS)) if (values[key] && !Object.hasOwn(catalog, values[key])) errors[key] = "Mã chưa có trong danh mục nghiệp vụ đã xác minh.";
  if (values.numberOfPage && !/^[1-6]$/u.test(values.numberOfPage)) errors.numberOfPage = "Số trang nguồn phải từ 1 đến 6.";
  return {errors, missing: FIELD_KEYS.filter(key => key !== "docId" && !values[key]),
    review: FIELD_KEYS.filter(key => draft.fields[key].status === "review"),
    unclassifiedMode: !values.mode};
}
export function serializeDocumentFields(draft) {
  const validation = validateDocumentDraft(draft);
  if (Object.keys(validation.errors).length) throw new Error(Object.values(validation.errors).join(" "));
  return JSON.stringify(documentValues(draft), null, 2);
}

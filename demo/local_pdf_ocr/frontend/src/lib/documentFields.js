import {MAX_FAST_SOURCE_PAGES} from "./processingModes.js";

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
const bodyStart = /^(?:Căn cứ(?=\s|$|[:,])|Kính gửi(?=\s|$|[:,])|Điều\s+\d|QUYẾT ĐỊNH\s*:|QUYẾT NGHỊ\s*:|Nơi nhận\s*:|PHỤ LỤC(?=\s|$|[:,])|DANH MỤC(?=\s|$|[:,])|KT\.|TM\.)/iu;
const national = /CỘNG HÒA|XÃ HỘI CHỦ NGHĨA|Độc lập\s*[-–—]|Tự do\s*[-–—]|Hạnh phúc/iu;
const issuer = /^(?:VĂN PHÒNG|ỦY BAN|HỘI ĐỒNG|BỘ\s|SỞ\s|PHÒNG\s|CỤC\s|TỔNG CỤC|CHÍNH PHỦ$|THỦ TƯỚNG CHÍNH PHỦ$|QUỐC HỘI$|TÒA ÁN|VIỆN KIỂM SÁT|CƠ QUAN\s)/iu;
const title = /^(NGHỊ ĐỊNH|NGHỊ QUYẾT|QUYẾT ĐỊNH|CÔNG VĂN|THÔNG BÁO|THÔNG TƯ|BÁO CÁO|KẾ HOẠCH|TỜ TRÌNH)$/iu;
const typeCodes = {"NGHỊ QUYẾT": "01", "QUYẾT ĐỊNH": "02", "CÔNG VĂN": "22"};
const typeLabels = {"NGHỊ ĐỊNH":"Nghị định","NGHỊ QUYẾT":"Nghị quyết","QUYẾT ĐỊNH":"Quyết định","CÔNG VĂN":"Công văn","THÔNG BÁO":"Thông báo","THÔNG TƯ":"Thông tư","BÁO CÁO":"Báo cáo","KẾ HOẠCH":"Kế hoạch","TỜ TRÌNH":"Tờ trình"};
// "Cơ quan phát hành:" is the signing portal's mark, not a second issuing agency.
const signatureMarker = /^(?:Cơ quan phát hành\s*:|Ký bởi\s*:|Người ký\s*:|Thời gian ký\s*:|Ngày ký(?: điện tử)?\s*:|Digitally signed(?:\s|$)|Signing time\s*:)/iu;
const arrivalMarker = /^(?:CÔNG VĂN\s+)?ĐẾN\s*[:：]?$/iu;
// The recognizer can misread the "Số:" label ("3ố:", "Ố:"); with its colon it is still the label.
// The value after it is kept exactly as read.
const numberLabel = /^(?:Số|[\p{L}\p{N}]?ố(?=\s*[:：﹕]))\s*(?:[:：﹕]\s*)?(.*)$/iu;
const exactNumberLabel = /^Số(?:\s|[:：﹕]|$)/iu;
// A number can be read with spaces between its digits ("2 1/2026/TT-BCT"); only digits before the first "/" are joined.
const spacedNumber = /^\d(?: \d)+(?=\s*\/)/u;
const joinNumberDigits = text => text.trim().replace(spacedNumber, digits => digits.replace(/ /gu, ""));
const subjectLabel = /^(?:V\/v\s*[:：]?|Về việc\s*[:：]?)\s*(.*)$/iu;
const codePattern = /^[\p{L}\p{N}\p{Pd}._?\uFFFD]+(?:\s*\/\s*[\p{L}\p{N}\p{Pd}._?\uFFFD]+)+/u;

function bounds(line, method) {
  const geometry = method === "metadata_fast" ? line.geometry_source : method;
  if (geometry === "native_text" && Array.isArray(line.bbox) && line.bbox.length === 4 && line.bbox.every(Number.isFinite)) return [...line.bbox];
  if (["vietocr_ocr", "hybrid_h1"].includes(geometry) && Array.isArray(line.polygon) && line.polygon.length === 4
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
        region: spatial ? box.map((value,index) => value / (index % 2 ? page.height : page.width)) : null,
        coordinateSystem: (result.method === "native_text" || result.method === "metadata_fast" && line.geometry_source === "native_text") ? "pdf_points" : "raster_pixels",
        precision: (result.method === "native_text" || result.method === "metadata_fast" && line.geometry_source === "native_text") ? "block" : "polygon",
        metadataExcludedReason: line.metadata_excluded_reason};
    // Ruling lines and underscores carry no text.
    }).filter(line => line.match && /[\p{L}\p{N}]/u.test(line.match));
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
// Text boxes on the same row just right of a line, in reading order: the detector can list a
// "Số:" label after its value when the value's box starts a little higher.
function sameRowRight(line, lines) {
  if (!line.region) return [];
  const [, top, right, bottom] = line.region;
  return lines.filter(other => other !== line && other.page === line.page && other.region
    && other.region[0] >= right - .01 && other.region[0] - right < .12
    && Math.min(bottom, other.region[3]) - Math.max(top, other.region[1])
      >= .5 * Math.min(bottom - top, other.region[3] - other.region[1]))
    .sort((a, b) => a.region[0] - b.region[0]);
}
function boundary(line) {
  return bodyStart.test(line.match) || national.test(line.match) || numberLabel.test(line.match)
    || /ngày\s+\d/iu.test(line.match) || title.test(line.match) || issuer.test(line.match);
}
function excludedMetadataLine(line, all) {
  if (line.metadataExcludedReason || signatureMarker.test(line.match)) return true;
  return line.block != null && all.some(other => other.page === line.page && other.block === line.block
    && (other.metadataExcludedReason === "electronic_signature" || signatureMarker.test(other.match)));
}
function stampRole(line) {
  if (arrivalMarker.test(line.match)) return "arrival";
  if (/^GIỜ\s*[:：]/iu.test(line.match)) return "time";
  if (/^(?:NGÀY(?: ĐẾN| NHẬN)?)\s*[:：]/iu.test(line.match)) return "date";
  // A document's ordinary "Số:" label is not evidence of an arrival stamp.
  if (/^SỐ ĐẾN\s*[:：]/iu.test(line.match)) return "number";
  return "";
}
function narrowStampLine(line) {
  return line.region && line.region[2] - line.region[0] <= .3
    && line.region[3] - line.region[1] <= .08 && line.match.length <= 44;
}
function stampFieldOnly(line) {
  const role=stampRole(line);
  if (role==="arrival") return true;
  const value=line.match.replace(/^[^:：]+[:：]\s*/u,"");
  // Handwriting in a stamp field often reads as noise ("0g/9/2026", "S", "29./6/2026"): short and
  // without two letters in a row, so it holds no word. "03/02/2025, Tiếp nhận hồ sơ" holds words: it is mixed.
  const noise=value.length<=16 && !/\p{L}{2}/u.test(value);
  if (role==="date") return noise || /^\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+\d{4}[.,;]?$/iu.test(value);
  return (role==="time" || role==="number") && noise;
}
function nearStampAnchor(anchor, line) {
  if (anchor.page !== line.page || !anchor.region || !line.region) return false;
  const a=anchor.region,b=line.region;
  const gapY=Math.max(0,a[1]-b[3],b[1]-a[3]);
  // Use the second marker's left prefix, never its full (possibly merged)
  // paragraph-wide box, to establish a separate stamp context.
  return gapY <= Math.min(.03,Math.max(.01,(a[3]-a[1])*1.25))
    && b[0] >= a[0]-.035 && b[0] <= a[2]+.06;
}
function stampClusters(lines) {
  const markers=lines.filter(line=>stampRole(line));
  const clusters=[];
  for (const anchor of markers.filter(line=>stampRole(line)==="arrival" && narrowStampLine(line))) {
    const companions=markers.filter(line=>stampRole(line)!=="arrival" && nearStampAnchor(anchor,line));
    if (!companions.length) continue;
    const members=[anchor,...companions],standalone=members.filter(line=>narrowStampLine(line) && stampFieldOnly(line));
    clusters.push({members,standalone});
  }
  return {clusters,excluded:new Set(clusters.flatMap(cluster=>cluster.standalone))};
}
// An arrival-stamp field can be read on one line with the subject words its box covers
// ("Ngày: 03.14./2024, Sửa đổi, bổ sung…"). When the field's value is short handwriting without two
// letters in a row and words follow, the line is split there: the field becomes a stamp line and the
// words stay document text. The two boxes are estimated from character counts ("block" precision).
// A narrow line, or a field whose value holds words, is left whole (it stays mixed evidence).
function splitStampFields(lines) {
  const anchors = lines.filter(line => stampRole(line) === "arrival" && narrowStampLine(line));
  if (!anchors.length) return lines;
  return lines.flatMap(line => {
    if (!["date", "time", "number"].includes(stampRole(line)) || narrowStampLine(line) || !line.region || !line.box
      || !anchors.some(anchor => nearStampAnchor(anchor, line))) return [line];
    const colon = line.match.search(/[:：]/u);
    const tokens = line.match.slice(colon + 1).trim().split(" ");
    const first = tokens.findIndex(token => /\p{L}{2}/u.test(token));
    const value = tokens.slice(0, first).join(" ");
    if (first < 1 || value.length > 16 || /^(?:giờ|ngày|tháng|năm)$/iu.test(tokens[first])
      || tokens.slice(first).join(" ").length < 12) return [line];
    const stampText = `${line.match.slice(0, colon + 1)} ${value}`, words = tokens.slice(first).join(" ");
    const share = stampText.length / line.match.length;
    const part = (text, from, to) => {
      const box = [...line.box], region = [...line.region];
      [box[0], box[2]] = [line.box[0] + from * (line.box[2] - line.box[0]), line.box[0] + to * (line.box[2] - line.box[0])];
      [region[0], region[2]] = [line.region[0] + from * (line.region[2] - line.region[0]), line.region[0] + to * (line.region[2] - line.region[0])];
      return {...line, text, match: text, box, region, x: (region[0] + region[2]) / 2, precision: "block", splitFromStamp: true};
    };
    return [part(stampText, 0, share), part(words, share, 1)];
  });
}
function subjectStampRisk(candidate, clusters) {
  return clusters.filter(cluster=>candidate.lines.some(line=>
    cluster.members.includes(line) && !cluster.standalone.includes(line)
    || line.region && cluster.standalone.some(stamp=> {
      if (line.page!==stamp.page) return false;
      const a=line.region,b=stamp.region;
      return Math.max(0,a[0]-b[2],b[0]-a[2]) <= .003
        && Math.max(0,a[1]-b[3],b[1]-a[3]) <= .003;
    })));
}
function subjectCandidates(anchor, lines) {
  // "Về việc …" under a title is kept as printed (the owner's records keep it). The official
  // letter's "V/v" label is still dropped.
  const tail = /^Về việc(?:\s|$)/iu.test(anchor.match) ? anchor.match : subjectLabel.exec(anchor.match)?.[1] ?? "";
  const used = [anchor], parts = tail ? [tail] : [];
  let limited = false;
  // Subject continuation is a paragraph after its own title, not the whole
  // identity header. In particular, cited dates/numbers are allowed here.
  for (const next of lines.filter(line => line.order > anchor.order && sameColumn(anchor, line))) {
    // Only an upper-case agency line ends a subject: "bộ và Trường..." or "Ủy ban nhân dân..." are its own words.
    if (bodyStart.test(next.match) || national.test(next.match) || title.test(next.match) || subjectLabel.test(next.match)
      || issuer.test(next.match) && next.match === next.match.toLocaleUpperCase("vi")) break;
    const previous = used.at(-1);
    if (next.y != null && previous.y != null && (next.y < previous.y - .005
      || next.y - previous.y > (parts.length ? .045 : .075))) break;
    // A paragraph gap: a step much larger than the subject's own line spacing (a consolidated
    // text's "Thông tư số ... được sửa đổi, bổ sung bởi:" paragraph follows its subject this way).
    const steps = used.slice(2).map((line, i) => line.y - used[i + 1].y).filter(step => step > 0);
    if (next.y != null && previous.y != null && steps.length && next.y - previous.y > Math.max(.025, 1.7 * Math.max(...steps))) break;
    parts.push(next.match); used.push(next);
    if (parts.length >= 24) {limited = true; break;}
  }
  return parts.length ? {value:parts.join(" "),lines:used,review:limited || parts.length >= 5,
    note:limited ? "Trích yếu đạt giới hạn đoạn; đối chiếu ảnh nguồn để xác nhận điểm kết thúc."
      : parts.length >= 5 ? "Tiêu đề dài; kiểm tra điểm kết thúc trích yếu." : ""} : null;
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
  const allLines = readLines(result);
  const metadataLines = splitStampFields(allLines.filter(line => !excludedMetadataLine(line, allLines)));
  const stamps = stampClusters(metadataLines);
  const lines = metadataLines.filter(line => !stamps.excluded.has(line));
  const headerPage = result?.method === "metadata_fast" ? result.pages?.[0]?.page ?? 1 : 1;
  const first = lines.filter(line => line.page === headerPage);
  const textualEnd = first.findIndex(line => bodyStart.test(line.match));
  const bodyY = first.filter(line => bodyStart.test(line.match) && line.y != null).map(line => line.y);
  const header = first.filter((line, i) => line.y != null
    // Fast results already contain a bounded, possibly expanded header ROI.
    // A long header below 45% remains usable until its first body anchor.
    ? line.y < Math.min(result?.method === "metadata_fast" ? Infinity : .44, ...bodyY)
    : i < (textualEnd < 0 ? result?.method === "metadata_fast" ? first.length : 24 : textualEnd));
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
    const followers = new Set([...(label[1].trim() ? [] : sameRowRight(line, identityHeader)), ...successors(line, identityHeader, 3)]);
    for (const next of followers) {
      if (codePattern.test(joinNumberDigits(candidate)) && !candidate.trim().endsWith("/")) break;
      if (boundary(next)) break;
      // Trim: a bare "Số:" leaves an empty start, and a leading space would hide a complete value.
      candidate = (candidate + " " + next.match).trim();
      used.push(next);
    }
    const misreadLabel = !exactNumberLabel.test(line.match);
    const spaced = spacedNumber.exec(candidate.trim())?.[0];
    const joined = joinNumberDigits(candidate);
    const matched = codePattern.exec(joined);
    if (matched) {
      if (joined.slice(matched[0].length).trim()) {
        incompleteCode = true;
        fields.arcDocCode = field("", "review", used, "Dòng số/ký hiệu có đoạn chưa phân tách rõ; cần kiểm tra nguyên bản.");
        continue;
      }
      const value = matched[0].replace(/\s*\/\s*/gu, "/").trim();
      const uncertain = !/^\d+\//u.test(value) || /[?\uFFFD]/u.test(value) || used.some(x => /\|/u.test(x.match));
      const note = [uncertain ? "Có ký tự OCR chưa chắc chắn; đối chiếu bản gốc. Không tự thay ký tự." : "",
        misreadLabel ? `Nhãn “Số” đọc thành “${line.match.split(/[:：﹕]/u)[0]}”; kiểm tra số/ký hiệu với bản gốc.` : "",
        spaced ? `Chữ số của số văn bản đọc bị tách (“${spaced}”); kiểm tra với bản gốc.` : ""].filter(Boolean).join(" ");
      codes.push({value, lines: used, review: uncertain || misreadLabel || Boolean(spaced), note});
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
    // A handwritten day or month can be read with a space between its two digits ("ngày 0 7 tháng").
    const regex = /^(?:[\p{L}\s.]{1,70},\s*)?ngày\s+(\d{1,2}|[0-3]\s\d)\s+tháng\s+(\d{1,2}|[01]\s\d)\s+năm\s+(\d{4})/giu;
    for (const match of text.matchAll(regex)) {
      const [day, month] = [match[1], match[2]].map(part => part.replace(/\s/gu, ""));
      const value = `${day.padStart(2, "0")}-${month.padStart(2, "0")}-${match[3]}`;
      const split = /\s/u.test(match[1] + match[2]);
      dates.push({value, lines: used, review: split, note: split ? `Chữ số ngày/tháng đọc bị tách (“ngày ${match[1]} tháng ${match[2]}”); kiểm tra với bản gốc.` : "",
        invalid: !isValidIssuedDate(value) || Boolean(text.slice(match[0].length).replace(/[.\s]/gu, ""))});
    }
  }
  if (dates.some(date => date.invalid)) fields.issuedDate = field("", "review", dates.flatMap(c => c.lines), "Ngày trong header không hợp lệ hoặc cạnh tranh; không tự sửa ngày/tháng.");
  else fields.issuedDate = choose(dates, "Có nhiều ngày ban hành cạnh tranh trong header; cần xác nhận.");

  const firstCodeY = Math.min(...header.filter(line => numberLabel.test(line.match)).map(line => line.y ?? Infinity));
  const agencies = identityHeader.filter(line => issuer.test(line.match) && !national.test(line.match)
    && (line.y == null || line.y < firstCodeY) && (line.x == null || line.x < .52));
  // The detector can merge the two header columns into one line: the agency is what precedes the national motto.
  const mergedColumns = identityHeader.flatMap(line => {
    const merged = /^(.+?)\s+CỘNG\s+H(?:ÒA|OÀ)(?=\s)/u.exec(line.match);
    return merged && issuer.test(merged[1]) ? [{value: merged[1].toLocaleUpperCase("vi"), lines: [line]}] : [];
  });
  const agencyCandidates = [...mergedColumns, ...agencies.map(line => {
    const used = [line];
    for (const next of successors(line, header, 2)) {
      if (boundary(next) || next.match !== next.match.toLocaleUpperCase("vi") || !/\p{L}/u.test(next.match)
        || (line.y != null && next.y - line.y > .065)) break;
      used.push(next);
    }
    return {value: used.map(x => x.match).join(" ").toLocaleUpperCase("vi"), lines: used};
  })];
  fields.organName = choose(agencyCandidates, "Header có nhiều cơ quan/cấp cơ quan; chưa xác định cơ quan ban hành.");

  const titles = header.filter(line => title.test(line.match));
  const classified = titles.map(line => ({value: typeCodes[line.match.toLocaleUpperCase("vi")], lines: [line]})).filter(c => c.value);
  fields.typeName = choose(classified, "Có nhiều loại văn bản cạnh tranh; cần kiểm tra.");
  if (new Set(titles.map(line => line.match.toLocaleUpperCase("vi"))).size > 1) fields.typeName = field("", "review", titles, "Có nhiều tiêu đề loại văn bản cạnh tranh; cần xác nhận.");
  if (!classified.length && titles.length) fields.typeName = field("", "review", titles, "Loại tài liệu chưa có mã nghiệp vụ được xác minh trong danh mục.");
  let typeLabel = titles.length === 1 ? typeLabels[titles[0].match.toLocaleUpperCase("vi")] || "" : "";
  const subjects = [];
  const explicit = header.filter(line => subjectLabel.test(line.match));
  const anchors = explicit.length ? explicit : titles;
  // An official letter has no title of its own. Its "V/v" line sits in the left column right under
  // "Số:" (the letter layout of Decree 30/2020); a "V/v" line elsewhere does not decide the type.
  const numberLines = header.filter(line => numberLabel.test(line.match));
  const letterSubject = explicit.find(line => line.region && line.region[2] < .5 && numberLines.some(number =>
    number.region && sameColumn(number, line) && line.region[1] >= number.region[1] && line.region[1] - number.region[3] < .06));
  if (!titles.length && letterSubject) {
    fields.typeName = field("22", "review", [...numberLines.filter(line => sameColumn(line, letterSubject)), letterSubject],
      "Suy ra từ bố cục công văn: dòng “V/v” ngay dưới số, không có tiêu đề loại văn bản; kiểm tra.");
    typeLabel = typeLabels["CÔNG VĂN"];
  }
  for (const line of anchors) {
    const candidate = subjectCandidates(line, first);
    if (candidate) subjects.push(candidate);
  }
  fields.subject = choose(subjects, "Có nhiều trích yếu cạnh tranh; chưa ghép tự động.");
  const contaminated=subjects.map(candidate=>({candidate,clusters:subjectStampRisk(candidate,stamps.clusters)})).filter(item=>item.clusters.length);
  // A mixed fragment outside the title's column must not make the remaining
  // paragraph look complete. Keep that orphan separately, without inventing
  // its position within the subject text.
  const orphanMixed=[...new Set(stamps.clusters.flatMap(cluster=>cluster.members))].filter(fragment=>
    !stampFieldOnly(fragment) && !subjects.some(candidate=>candidate.lines.includes(fragment))
    && anchors.some(anchor=> {
      const end=first.find(line=>line.order>anchor.order && bodyStart.test(line.match));
      return fragment.page===anchor.page && fragment.order>anchor.order && fragment.order<(end?.order ?? Infinity)
        && (fragment.y==null || anchor.y==null || fragment.y>=anchor.y-.005);
    }));
  // A subject whose lines only touch an arrival stamp read as its own line(s) holds none of the stamp's
  // text: it is filled, for review. Stamp text read inside a subject line (mixed) keeps it empty.
  const mixedSubject=contaminated.some(({candidate,clusters})=>candidate.lines.some(line=>
    clusters.some(cluster=>cluster.members.includes(line) && !cluster.standalone.includes(line))));
  if (contaminated.length && !mixedSubject && !orphanMixed.length && fields.subject.value) {
    const implicated=[...new Set(contaminated.flatMap(item=>item.clusters))];
    const stampParts=implicated.flatMap(cluster=>cluster.members).filter(line=>line.splitFromStamp);
    const sources=[...new Set([...subjects.flatMap(candidate=>candidate.lines),...implicated.flatMap(cluster=>cluster.members)])]
      .sort((a,b)=>a.order-b.order);
    fields.subject={...fields.subject,status:"review",evidence:evidence(sources),note:[fields.subject.note,
      "Dấu công văn đến chạm vào dòng trích yếu; chữ của dấu được đọc riêng, không nằm trong trích yếu. Đối chiếu ảnh nguồn, nhất là các chữ sát dấu.",
      ...stampParts.map(line=>`Ô “${line.match}” của dấu đọc chung dòng với trích yếu và đã được tách ra theo vị trí chữ.`)]
      .filter(Boolean).join(" ")};
  } else if (contaminated.length || orphanMixed.length) {
    const implicated=[...new Set([...contaminated.flatMap(item=>item.clusters),
      ...stamps.clusters.filter(cluster=>cluster.members.some(line=>orphanMixed.includes(line)))])];
    const sources=[...new Set([...anchors,...subjects.flatMap(candidate=>candidate.lines),
      ...implicated.flatMap(cluster=>cluster.members)])].sort((a,b)=>a.order-b.order);
    fields.subject={...field("", "review", sources,
      "Trích yếu chưa xác minh: dấu công văn đến nằm sát hoặc đóng chồng lên vùng chữ. Đối chiếu ảnh nguồn và nhập lại; ứng viên nghi ngờ không được đưa vào JSON/Excel."),
      candidate:[...new Set([...subjects.map(candidate=>candidate.value),...orphanMixed.map(line=>line.text)])].join("\n\n")};
  }
  if (!subjects.length && titles.length && !orphanMixed.length) fields.subject = field("", "review", titles, "Chưa đọc đủ đoạn trích yếu sau tiêu đề; đối chiếu ảnh nguồn.");

  // Ký hiệu thông tin: the short mark written in the top-right corner of page 1, above the national
  // motto (owner's round-1 records: "TTĐT", "TTĐT(2)"). Kept exactly as read and always for review:
  // handwriting is often misread. Printed urgency/secrecy marks there are not this field.
  const motto = first.find(line => national.test(line.match) && line.region);
  const marks = first.filter(line => line.region && line.region[0] >= .72 && line.region[1] < .12
    && line.region[3] <= (motto ? motto.region[1] + .01 : .12) && /^[\p{Lu}\p{N}()\s./-]{2,12}$/u.test(line.match)
    && (line.match.match(/\p{Lu}/gu) ?? []).length >= 2
    && !/^(?:MẬT|TỐI MẬT|TUYỆT MẬT|KHẨN|THƯỢNG KHẨN|HỎA TỐC|HOẢ TỐC|DỰ THẢO|BẢN SAO)$/u.test(line.match));
  // A mark is one handwritten code: a space read inside it ("TTĐ T") is removed, and said so.
  if (marks.length === 1) fields.inforSign = field(marks[0].match.replace(/\s/gu, ""), "review", marks,
    ["Ký hiệu viết tay ở góc trên bên phải trang 1, giữ nguyên chữ OCR đọc; chữ viết tay hay bị đọc sai, đối chiếu bản gốc.",
      /\s/u.test(marks[0].match) ? `OCR đọc “${marks[0].match}”; đã bỏ khoảng trắng bên trong.` : ""].filter(Boolean).join(" "));
  else if (marks.length > 1) fields.inforSign = field("", "review", marks, "Góc trên bên phải trang 1 có nhiều ký hiệu; chọn tay.");

  const vi = lines.filter(line => national.test(line.match) || /\b(?:ngày|tháng|năm|việc|văn bản|quyết định|nghị quyết|nghị định)\b/iu.test(line.match));
  const en = lines.filter(line => /\b(?:REPUBLIC|GOVERNMENT|DECISION|RESOLUTION)\b/u.test(line.match) || /\b(?:the|and|of|for)\b/giu.test(line.match) && /\b(?:document|issued|administrative|decision)\b/iu.test(line.match));
  if (vi.length && en.length) fields.language = field("", "review", [vi[0], en[0]], "Có bằng chứng nhiều ngôn ngữ; cần xác nhận.");
  else if (vi.length >= 2 || vi.some(line => national.test(line.match))) fields.language = field("01", "recognized", vi.slice(0, 2));
  else if (en.length >= 2) fields.language = field("02", "recognized", en.slice(0, 2));

  const fast = result?.method === "metadata_fast";
  const count = fast ? result?.source_page_count : sourceKind === "image" ? 1 : result?.page_count;
  if (Number.isInteger(count) && count >= 1 && count <= (fast ? MAX_FAST_SOURCE_PAGES : 6) && Array.isArray(result?.pages)
    && (fast ? result.pages.length > 0 && result.pages.length <= count : result.pages.length === count)) {
    fields.numberOfPage = {...field(String(count), "recognized"), evidence: [{text: fast ? `Bộ đọc nguồn trả về source_page_count = ${count}; kết quả chỉ chứa vùng header đã xét.`
      : sourceKind === "image" ? "Ảnh nguồn: 1 trang." : `Bộ đọc PDF nguồn trả về page_count = ${count}.`, source: "source_page_count"}]};
  }
  fields.confidenceLevel = {...field("02", "review"), note: "Mã nghiệp vụ, không phải độ chính xác OCR. isCan chưa xác định vẫn thuộc trường hợp khác → 02.", evidence: [{source: "business_rule", text: 'isCan = "0" → 01; các trường hợp khác → 02.'}]};
  // Literal OCR evidence proves the extraction source, not the correctness of its characters.
  // There is no calibrated recognizer confidence: require visual review for all OCR-derived text.
  if (["vietocr_ocr", "hybrid_h1"].includes(result?.method) || fast && result?.used_ocr) {
    for (const entry of Object.values(fields)) if (entry.value && entry.status === "recognized" && entry.evidence.some(source => source.page)) {
      entry.status = "review";
      entry.note = [entry.note, "Nguồn OCR: đối chiếu bản gốc trước khi xác nhận; không tự sửa chữ hoặc dấu."].filter(Boolean).join(" ");
    }
  }
  if (fast && result.fast_metadata?.needs_review) {
    fields.subject.status = "review";
    fields.subject.note = [fields.subject.note, "Kết quả header một phần: đối chiếu trích yếu với ảnh nguồn, nhất là vùng dấu đóng chồng hoặc dòng bị cắt."].filter(Boolean).join(" ");
  }
  // Seal colour comes from the page pixels (backend seal_colour.py), not from OCR text.
  const seal = result?.seal;
  if (seal?.reason === "found" && seal.colour === "red" && Number.isInteger(seal.page)) {
    const size = Array.isArray(seal.size_mm) ? ` khoảng ${seal.size_mm.map(v => Math.round(v)).join(" × ")} mm` : "";
    const source = {source: "seal_colour", sealPage: seal.page, text: `Trang ${seal.page}: dấu tròn màu đỏ${size}.`};
    fields.isCan = {...field("0", "recognized"), evidence: [source], note: "Nhận diện từ màu và hình dạng con dấu trên ảnh trang, không phải OCR."};
    fields.confidenceLevel = {...field("01", "recognized"), evidence: [source, {source: "business_rule", text: 'isCan = "0" → 01.'}],
      note: "Tính từ màu con dấu đỏ nhận diện tự động. Mã nghiệp vụ, không phải độ chính xác OCR."};
  } else if (seal?.reason === "black_and_white") {
    fields.isCan.note = "Bản quét đen trắng: không xác định được màu con dấu từ ảnh; đối chiếu bản gốc.";
  } else if (seal?.reason === "not_found") {
    fields.isCan.note = `Không thấy dấu tròn màu đỏ trên ${seal.pages_checked?.length ?? 0} trang đã xét; đối chiếu bản gốc.`;
  }
  return {fields, dirty: false, method: result?.method ?? "", typeLabel};
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
  // Full-text modes read at most 6 pages; the fast header mode reports the page count of longer sources.
  if (values.numberOfPage && !(/^[1-9]\d*$/u.test(values.numberOfPage) && Number(values.numberOfPage) <= MAX_FAST_SOURCE_PAGES))
    errors.numberOfPage = `Số trang nguồn phải là số nguyên từ 1 đến ${MAX_FAST_SOURCE_PAGES}.`;
  return {errors, missing: FIELD_KEYS.filter(key => key !== "docId" && !values[key]),
    review: FIELD_KEYS.filter(key => draft.fields[key].status === "review"),
    unclassifiedMode: !values.mode};
}
export function serializeDocumentFields(draft) {
  const validation = validateDocumentDraft(draft);
  if (Object.keys(validation.errors).length) throw new Error(Object.values(validation.errors).join(" "));
  return JSON.stringify(documentValues(draft), null, 2);
}

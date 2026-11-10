// Fast mode opens only page 1, so its PDF may be longer than the full-text modes allow (backend MAX_FAST_SOURCE_PAGES).
export const MAX_FAST_SOURCE_PAGES = 1000;
export const FAST_MODE_LABEL = "Bóc tách nhanh thông tin văn bản";
export const FAST_MODE_DESCRIPTION = "Lấy 22 trường từ trang đầu (số văn bản, ngày ban hành, cơ quan, trích yếu…). Không OCR toàn bộ tài liệu.";
// Run buttons: one for the selected document, one (emphasized when several are listed) for the whole list.
export const RUN_ONE_LABEL = "Bóc tách văn bản này";
export const RUN_ONE_FAST_LABEL = "Bóc tách nhanh văn bản này";
export const RUN_ALL_LABEL = "Bóc tách tất cả";
export const runAllLabel = count => `${RUN_ALL_LABEL} (${count} tài liệu)`;
// Once the selected method has a result, running again is a secondary action, not the next step.
export const RERUN_ONE_LABEL = "Bóc tách lại";
export const RERUN_THIS_LABEL = "Bóc tách lại văn bản này";
export const rerunAllLabel = count => `Bóc tách lại tất cả (${count} tài liệu)`;
export const RESUME_LABEL = "Tiếp tục";
export const resumeLabel = left => `${RESUME_LABEL} (${left} tài liệu còn lại)`;
export const PROCESSING_MODES = ["native_text", "vietocr_ocr", "hybrid_h1", "metadata_fast"];
export const PROCESSING_LABELS = {native_text:"Văn bản có sẵn",vietocr_ocr:"Nhận dạng OCR",hybrid_h1:"Kết hợp PDF + OCR (thử nghiệm)",metadata_fast:"Bóc tách nhanh · Header một phần"};

// A consolidated text without a page-1 header also has its authentication block read (backend consolidation_block).
const BLOCK_SOURCES = {native_text: "lớp chữ PDF", vietocr_ocr: "OCR"};
export function partialScope(result) {
  const inspected = result.inspected_pages?.join(", ") || "chưa xác định";
  const processed = result.processed_pages?.length ? `OCR trang ${result.processed_pages.join(", ")}` : "không chạy OCR";
  const block = result.consolidation_block;
  const blockScope = block ? ` · Khối xác thực văn bản hợp nhất: trang ${block.page} (${BLOCK_SOURCES[block.read_by] ?? "không rõ nguồn"})` : "";
  return `Nguồn ${result.source_page_count ?? "—"} trang · Đã xét trang ${inspected} · ${processed}${blockScope}`;
}
export function resultTextExport(result, text = result.text || "") {
  return result.method === "metadata_fast"
    ? `BÓC TÁCH NHANH — NỘI DUNG HEADER MỘT PHẦN\n${partialScope(result)}\nKhông phải toàn văn tài liệu.\n\n${text}`
    : text;
}
export function validateFastResult(data) {
  const page = data.pages?.[0], roi = page?.roi;
  const sourceCoordinates = data.used_ocr ? "raster_pixels" : "pdf_points";
  const sourceGeometry = data.used_ocr ? "vietocr_ocr" : "native_text";
  const onePage = values => Array.isArray(values) && values.length === 1 && values[0] === 1;
  const finite = value => typeof value === "number" && Number.isFinite(value);
  const validPage = page && finite(page.width) && page.width > 0 && finite(page.height) && page.height > 0
    && page.coordinate_system === sourceCoordinates && Array.isArray(roi) && roi.length === 4 && roi.every(finite)
    && roi[0] >= 0 && roi[1] >= 0 && roi[2] > roi[0] && roi[3] > roi[1]
    && roi[2] <= page.width + 1 && roi[3] <= page.height + 1
    && roi[3] <= Math.ceil(page.height * .8) + 1;
  const validLines = Array.isArray(page?.lines) && page.lines.every((line,index) => line && typeof line.text === "string"
    && line.line_index === index + 1 && line.geometry_source === sourceGeometry);
  const validText = validLines && typeof data.text === "string" && page.text === data.text
    && page.lines.map(line => line.text).join("\n") === data.text
    && Number.isInteger(data.line_count) && data.line_count === page.lines.length;
  // Optional: a consolidated text's authentication block, one page after page 1, read from the text layer or by OCR.
  const block = data.consolidation_block;
  const validBlock = block === undefined || Boolean(block) && Number.isInteger(block.page) && block.page > 1
    && block.page <= data.source_page_count && finite(block.width) && block.width > 0 && finite(block.height) && block.height > 0
    && {native_text: "pdf_points", vietocr_ocr: "raster_pixels"}[block.read_by] === block.coordinate_system
    && ["text_layer", "red_seal"].includes(block.located_by) && Array.isArray(block.lines) && block.lines.length > 0
    && block.lines.every((line, index) => line && typeof line.text === "string" && line.line_index === index + 1
      && line.geometry_source === block.read_by && (block.read_by === "native_text"
        ? Array.isArray(line.bbox) && line.bbox.length === 4 && line.bbox.every(finite)
        : Array.isArray(line.polygon) && line.polygon.length >= 4
          && line.polygon.every(point => Array.isArray(point) && point.length === 2 && point.every(finite))))
    && block.text === block.lines.map(line => line.text).join("\n");
  if (data.partial_result !== true || !Number.isInteger(data.source_page_count) || data.source_page_count < 1 || data.source_page_count > MAX_FAST_SOURCE_PAGES
    || !onePage(data.inspected_pages)
    || !Array.isArray(data.processed_pages) || !(data.processed_pages.length === 0 || onePage(data.processed_pages))
    || !Array.isArray(data.pages) || data.page_count !== 1 || data.pages.length !== 1 || page?.page !== 1
    || typeof data.used_ocr !== "boolean" || data.used_ocr !== Boolean(data.processed_pages.length)
    || !["header_native_text", "header_ocr"].includes(data.source)
    || (data.source === "header_native_text") !== !data.used_ocr
    || !validPage || !validText || !validBlock
    || typeof data.fast_metadata?.needs_review !== "boolean" || typeof data.fast_metadata?.header_complete !== "boolean") {
    throw Error("Kết quả bóc tách nhanh thiếu hoặc sai thông tin số trang nguồn/phạm vi header; không dùng như toàn văn.");
  }
}

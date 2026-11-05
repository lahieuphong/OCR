// Fast mode opens only page 1, so its PDF may be longer than the full-text modes allow (backend MAX_FAST_SOURCE_PAGES).
export const MAX_FAST_SOURCE_PAGES = 1000;
export const FAST_MODE_LABEL = "Bóc tách nhanh thông tin văn bản";
export const FAST_MODE_DESCRIPTION = "Ưu tiên trang đầu để lấy số văn bản, ngày ban hành, cơ quan, trích yếu và 22 trường metadata. Không OCR toàn bộ tài liệu.";
// Run buttons: one for the selected document, one (emphasized when several are listed) for the whole list.
export const RUN_ONE_LABEL = "Bóc tách văn bản này";
export const RUN_ONE_FAST_LABEL = "Bóc tách nhanh văn bản này";
export const RUN_ALL_LABEL = "Bóc tách tất cả";
export const RUN_ALL_DONE_LABEL = "Đã bóc tách tất cả tài liệu";
export const runAllLabel = pending => `${RUN_ALL_LABEL} (${pending} tài liệu)`;
export const PROCESSING_MODES = ["native_text", "vietocr_ocr", "hybrid_h1", "metadata_fast"];
export const PROCESSING_LABELS = {native_text:"Văn bản có sẵn",vietocr_ocr:"Nhận dạng OCR",hybrid_h1:"Kết hợp PDF + OCR (thử nghiệm)",metadata_fast:"Bóc tách nhanh · Header một phần"};

export function partialScope(result) {
  const inspected = result.inspected_pages?.join(", ") || "chưa xác định";
  const processed = result.processed_pages?.length ? `OCR trang ${result.processed_pages.join(", ")}` : "không chạy OCR";
  return `Nguồn ${result.source_page_count ?? "—"} trang · Đã xét trang ${inspected} · ${processed}`;
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
  if (data.partial_result !== true || !Number.isInteger(data.source_page_count) || data.source_page_count < 1 || data.source_page_count > MAX_FAST_SOURCE_PAGES
    || !onePage(data.inspected_pages)
    || !Array.isArray(data.processed_pages) || !(data.processed_pages.length === 0 || onePage(data.processed_pages))
    || !Array.isArray(data.pages) || data.page_count !== 1 || data.pages.length !== 1 || page?.page !== 1
    || typeof data.used_ocr !== "boolean" || data.used_ocr !== Boolean(data.processed_pages.length)
    || !["header_native_text", "header_ocr"].includes(data.source)
    || (data.source === "header_native_text") !== !data.used_ocr
    || !validPage || !validText
    || typeof data.fast_metadata?.needs_review !== "boolean" || typeof data.fast_metadata?.header_complete !== "boolean") {
    throw Error("Kết quả bóc tách nhanh thiếu hoặc sai thông tin số trang nguồn/phạm vi header; không dùng như toàn văn.");
  }
}

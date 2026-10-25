import {createDocumentDraft, validateDocumentDraft} from "./documentFields.js";

export const BATCH_STATUS_LABELS = {pending:"Chưa xử lý", processing:"Đang xử lý", extracted:"Đã bóc tách", review:"Cần kiểm tra", error:"Lỗi", confirmed:"Đã xác nhận"};
export function createBatchDocument(file, id = crypto.randomUUID()) {
  return {id, file, name:file.name, mode:/\.pdf$/iu.test(file.name) ? "native_text" : "vietocr_ocr",
    resultsByMode:{}, metadataByMode:{}, errorsByMode:{}, statesByMode:{}, confirmedByMode:{}, includeInExport:true};
}
export function batchReducer(documents, action) {
  if (action.type === "add") return [...documents, ...action.documents];
  if (action.type === "remove") return documents.filter(doc => doc.id !== action.id);
  if (action.type === "replace") return documents.map(doc => doc.id === action.id ? action.document : doc);
  if (action.type === "update") return documents.map(doc => doc.id === action.id ? action.update(doc) : doc);
  return documents;
}
export function batchDocumentStatus(doc) {
  if (doc.statesByMode[doc.mode] === "processing") return "processing";
  if (doc.errorsByMode[doc.mode]) return "error";
  if (!doc.resultsByMode[doc.mode] || !doc.metadataByMode[doc.mode]) return "pending";
  const validation = validateDocumentDraft(doc.metadataByMode[doc.mode]);
  if (Object.keys(validation.errors).length) return "review";
  if (doc.confirmedByMode[doc.mode]) return "confirmed";
  return validation.missing.length || validation.review.length ? "review" : "extracted";
}
export function batchExportState(documents) {
  const ready = documents.filter(doc => doc.includeInExport && doc.resultsByMode[doc.mode] && doc.metadataByMode[doc.mode]
    && !doc.errorsByMode[doc.mode] && doc.statesByMode[doc.mode] !== "processing"
    && Object.keys(validateDocumentDraft(doc.metadataByMode[doc.mode]).errors).length === 0);
  const unresolved = documents.filter(doc => !doc.resultsByMode[doc.mode] || doc.errorsByMode[doc.mode]
    || (doc.metadataByMode[doc.mode] && Object.keys(validateDocumentDraft(doc.metadataByMode[doc.mode]).errors).length));
  const drafts = ready.filter(doc => {
    const v = validateDocumentDraft(doc.metadataByMode[doc.mode]);
    return v.missing.length || v.review.length;
  });
  const unclassified = ready.filter(doc => validateDocumentDraft(doc.metadataByMode[doc.mode]).unclassifiedMode);
  return {ready, unresolved, drafts, unclassified};
}

export async function requestDocumentOcr(doc, request = fetch) {
  const payload = new FormData();
  payload.append("file", doc.file, doc.name);
  payload.append("mode", doc.mode);
  const response = await request("/api/ocr", {method:"POST",body:payload});
  let data;
  try {data = await response.json();}
  catch {throw Error("Không đọc được phản hồi từ máy chủ xử lý. Vui lòng thử lại hoặc mở log trong cửa sổ trạng thái.");}
  if (!response.ok) throw Error(data.detail || "Không thể bóc tách văn bản. Vui lòng thử lại.");
  if (data.method !== doc.mode) throw Error("Backend trả sai chế độ xử lý đã chọn; dừng để bảo vệ kết quả.");
  if (!Array.isArray(data.pages)) throw Error("Định dạng phản hồi từ backend không hợp lệ.");
  if (doc.mode === "native_text" && !data.text?.trim()) throw Error("PDF không có lớp chữ có thể trích xuất. Hãy chọn Nhận dạng OCR cho tài liệu này nếu cần; ứng dụng không tự chuyển phương pháp.");
  return {raw:data, draft:createDocumentDraft(data, {sourceKind:/\.pdf$/iu.test(doc.name) ? "pdf" : "image"})};
}

// Await each request, including errors, before starting the next one. No fallback or parallel requests.
export async function runDocumentQueue(documents, {request = fetch, onStart = () => {}, onSuccess = () => {}, onError = () => {}, onProgress = () => {}, shouldContinue = () => true} = {}) {
  for (let index = 0; index < documents.length; index++) {
    if (!shouldContinue()) break;
    const doc = documents[index];
    onStart(doc);
    try {onSuccess(doc, await requestDocumentOcr(doc, request));}
    catch (error) {onError(doc, error?.message || String(error));}
    onProgress(index + 1, documents.length);
  }
}

import {batchDocumentStatus} from "./documentBatch.js";

// How the left list is viewed when it holds hundreds of documents. Search and filters only change
// what is shown: "Bóc tách tất cả" always runs the whole list.
export const QUEUE_FILTERS = [
  {key:"all",label:"Tất cả"},
  {key:"pending",label:"Chưa xử lý"},
  {key:"done",label:"Đã xong"},
  {key:"review",label:"Cần kiểm tra"},
  {key:"error",label:"Lỗi"},
];
const FILTER_OF_STATUS = {pending:"pending",processing:"pending",extracted:"done",confirmed:"done",review:"review",error:"error"};

// Names are often typed without accents: "quyet dinh" finds "Quyết định".
export function searchKey(text) {
  return String(text ?? "").normalize("NFD").replace(/\p{M}/gu, "").replace(/đ/giu, "d").toLowerCase();
}
export function queueRows(documents) {
  return documents.map((doc, index) => {
    const status = batchDocumentStatus(doc);
    return {doc, index, status, group:FILTER_OF_STATUS[status], key:searchKey(doc.path || doc.name)};
  });
}
export function queueCounts(rows) {
  const counts = {pending:0,done:0,review:0,error:0};
  for (const row of rows) counts[row.group]++;
  return counts;
}
export function visibleRows(rows, {query = "", filter = "all"} = {}) {
  const terms = searchKey(query).split(/\s+/u).filter(Boolean);
  return rows.filter(row => (filter === "all" || row.group === filter) && terms.every(term => row.key.includes(term)));
}
// "Hồ sơ/2026/a.pdf" -> "2026": the chosen folder repeats on every row, so only what is below it is shown.
export function subfolder(path) {
  return String(path ?? "").split("/").slice(1, -1).join("/");
}

import {FIELD_KEYS, FIELD_LABELS, documentValues, validateDocumentDraft} from "./documentFields.js";
import {batchExportState, batchDocumentStatus, BATCH_STATUS_LABELS} from "./documentBatch.js";

export const EXCEL_FILENAME = "Danh_sach_van_ban.xlsx";
export const EXCEL_SHEET = "Danh sách văn bản";
export const EXCEL_HEADERS = ["STT", ...FIELD_KEYS.map(key => FIELD_LABELS[key])];
const widths = [7,18,28,20,20,17,25,19,42,64,16,12,22,32,22,23,30,23,21,23,25,50,21];
const invalidXml = /[\u0000-\u0008\u000B\u000C\u000E-\u001F]/u;
function safeString(value, label) {
  if (typeof value !== "string") throw Error(`${label}: giá trị phải là chuỗi.`);
  if (value.length > 32767) throw Error(`${label}: vượt giới hạn 32.767 ký tự của một ô Excel. Vui lòng rút gọn hoặc xuất JSON.`);
  if (invalidXml.test(value)) throw Error(`${label}: có ký tự điều khiển không hợp lệ trong XLSX. Vui lòng kiểm tra dữ liệu.`);
  return value;
}
function rowHeight(values, columnWidths) {
  return Math.min(120, Math.max(26, ...values.map((v, i) =>
    String(v ?? "").split(/\r?\n/u).reduce((n, line) => n + Math.max(1, Math.ceil(Array.from(line).length / Math.max(5, columnWidths[i] - 3))), 0) * 18 + 8)));
}
function styleTable(sheet, headers, values, columnWidths) {
  sheet.columns = headers.map((header, i) => ({header, key:String(i), width:columnWidths[i]}));
  for (const value of values) sheet.addRow(value);
  sheet.views = [{state:"frozen",xSplit:1,ySplit:1,topLeftCell:"B2",activePane:"bottomRight",showGridLines:false}];
  sheet.autoFilter = {from:{row:1,column:1},to:{row:values.length + 1,column:headers.length}};
  sheet.eachRow({includeEmpty:true}, (row, rowIndex) => {
    row.height = rowIndex === 1 ? 48 : rowHeight(Array.from({length:headers.length}, (_, i) => row.getCell(i + 1).value), columnWidths);
    for (let column = 1; column <= headers.length; column++) {
      const cell = row.getCell(column);
      cell.font = {name:"Times New Roman",size:13,bold:rowIndex === 1,color:{argb:"FF0F172A"}};
      cell.fill = {type:"pattern",pattern:"solid",fgColor:{argb:rowIndex === 1 ? "FFDBEAFE" : "FFFFFFFF"}};
      cell.border = Object.fromEntries(["top","left","bottom","right"].map(side => [side,{style:"thin",color:{argb:"FFCBD5E1"}}]));
      cell.alignment = {vertical:"top",horizontal:rowIndex === 1 || column === 1 ? "center" : "left",wrapText:true};
      cell.numFmt = column === 1 && rowIndex > 1 ? "0" : "@";
    }
  });
}

export async function createDocumentWorkbook(documents) {
  const selection = batchExportState(documents);
  if (!selection.ready.length) throw Error("Chưa có tài liệu hợp lệ để xuất Excel.");
  const rows = selection.ready.map((doc, index) => {
    const draft = doc.metadataByMode[doc.mode];
    if (Object.keys(validateDocumentDraft(draft).errors).length) throw Error("Metadata chưa hợp lệ.");
    const values = documentValues(draft);
    return [index + 1, ...FIELD_KEYS.map(key => {
      const text = safeString(values[key], `${doc.name} · ${FIELD_LABELS[key]}`);
      return text === "" ? null : text;
    })];
  });
  // ExcelJS's document writer is bundled locally by Vite, in a separate lazy chunk.
  const imported = await import("exceljs");
  const ExcelJS = imported.default || imported;
  const book = new ExcelJS.Workbook();
  book.creator = "VietDoc OCR";
  book.lastModifiedBy = "VietDoc OCR";
  styleTable(book.addWorksheet(EXCEL_SHEET), EXCEL_HEADERS, rows, widths);
  const sources = selection.ready.map((doc, index) => [index + 1,
    safeString(doc.name.replace(/^.*[\\/]/u,""), "Tên file"), doc.mode, BATCH_STATUS_LABELS[batchDocumentStatus(doc)]]);
  styleTable(book.addWorksheet("Nguồn tài liệu"), ["STT","Tên file","Phương pháp xử lý","Trạng thái xác nhận"], sources, [7,46,24,28]);
  // Primitive strings are stored as XLSX string cells, never as formula/hyperlink objects.
  return book.xlsx.writeBuffer();
}

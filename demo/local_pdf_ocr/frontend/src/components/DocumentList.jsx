import {useState} from "react";
import {FileSpreadsheet, LoaderCircle, RotateCcw, Check} from "lucide-react";
import {Button} from "@/components/ui/button";
import {Badge} from "@/components/ui/badge";
import ConfirmDialog from "./ConfirmDialog.jsx";
import {CATALOGS, documentValues} from "@/lib/documentFields.js";
import {batchDocumentStatus, batchExportState, BATCH_STATUS_LABELS} from "@/lib/documentBatch.js";
import {createDocumentWorkbook} from "@/lib/excelExport.js";

export default function DocumentList({documents,working,onSelect,onRetry,onConfirm,onIncluded,onDownload}) {
  const [confirmExport,setConfirmExport] = useState(false), [exporting,setExporting] = useState(false), [error,setError] = useState("");
  const selection = batchExportState(documents);
  const statuses = documents.map(batchDocumentStatus);
  async function exportExcel() {
    setConfirmExport(false); setExporting(true); setError("");
    try {onDownload(await createDocumentWorkbook(documents));}
    catch (exception) {setError(exception?.message || "Không thể tạo file Excel.");}
    finally {setExporting(false);}
  }
  function requestExport() {
    if (selection.unresolved.length || selection.drafts.length || selection.ready.length < documents.length) setConfirmExport(true);
    else exportExcel();
  }
  return <section className="document-list" aria-label="Danh sách văn bản">
    <div className="batch-summary"><span>Tổng: <b>{documents.length}</b></span><span>Đã bóc tách: <b>{documents.filter(doc => doc.resultsByMode[doc.mode] && !doc.errorsByMode[doc.mode]).length}</b></span><span>Cần kiểm tra: <b>{statuses.filter(s=>s==="review").length}</b></span><span>Lỗi: <b>{statuses.filter(s=>s==="error").length}</b></span></div>
    <div className="excel-toolbar"><Button className="excel-export-button" size="sm" disabled={working || exporting || !selection.ready.length} onClick={requestExport}>
      {exporting ? <LoaderCircle className="spin"/> : <FileSpreadsheet/>}{exporting ? "Đang tạo Excel…" : "Xuất danh sách Excel"}</Button>
      <span>{selection.ready.length} tài liệu được chọn · 23 cột · Times New Roman 13</span></div>
    {error && <p className="metadata-errors" role="alert">{error}</p>}
    {!documents.length ? <p className="batch-empty">Chọn một hoặc nhiều PDF để bắt đầu lập danh sách.</p> : <div className="batch-table-scroll"><table className="batch-table">
      <thead><tr><th>Chọn</th><th>STT</th><th>Mã văn bản / Tài liệu</th><th>Loại</th><th>Ngày ban hành</th><th>Cơ quan / Trích yếu</th><th>Trạng thái</th></tr></thead>
      <tbody>{documents.map((doc,index) => {
        const draft=doc.metadataByMode[doc.mode], values=draft ? documentValues(draft) : {}, status=batchDocumentStatus(doc);
        const ready=selection.ready.some(item=>item.id===doc.id);
        const eligible=Boolean(draft && doc.resultsByMode[doc.mode] && !doc.errorsByMode[doc.mode]);
        return <tr key={doc.id} data-document-id={doc.id}>
          <td><input type="checkbox" aria-label={`Xuất tài liệu ${index+1}: ${doc.name}`} checked={doc.includeInExport} disabled={working || !eligible} onChange={e=>onIncluded(doc.id,e.target.checked)}/></td>
          <td>{index+1}</td>
          <td><button className="open-document" onClick={()=>onSelect(doc.id,"metadata")} aria-label={`Mở thông tin tài liệu ${index+1}: ${doc.name}`}>{values.arcDocCode || doc.name}</button><small>{doc.name}</small><small>{doc.mode === "native_text" ? "Văn bản có sẵn" : doc.mode === "hybrid_h1" ? "Kết hợp PDF + OCR (thử nghiệm)" : "Nhận dạng OCR"}</small></td>
          <td>{CATALOGS.typeName[values.typeName] || "—"}</td><td>{values.issuedDate || "—"}</td>
          <td><strong>{values.organName || "—"}</strong><p>{values.subject || "Chưa xác định trích yếu"}</p></td>
          <td><Badge variant="outline" className={"batch-status " + status}>{BATCH_STATUS_LABELS[status]}</Badge>
            {doc.errorsByMode[doc.mode] && <p className="metadata-errors">{doc.errorsByMode[doc.mode]}</p>}
            {status === "error" && <Button variant="ghost" size="sm" disabled={working} onClick={()=>onRetry(doc.id)}><RotateCcw/> Thử lại</Button>}
            {ready && status !== "confirmed" && <Button variant="ghost" size="sm" disabled={working} aria-label={`Xác nhận tài liệu ${index+1}`} onClick={()=>onConfirm(doc.id)}><Check/> Xác nhận</Button>}
          </td>
        </tr>;
      })}</tbody>
    </table></div>}
    {confirmExport && <ConfirmDialog title="Xuất danh sách cần kiểm tra" confirmLabel="Xuất Excel đã chọn" onCancel={()=>setConfirmExport(false)} onConfirm={exportExcel}>
      <p>Xuất {selection.ready.length}/{documents.length} tài liệu đã chọn và có kết quả hợp lệ. {selection.unresolved.length} tài liệu chưa xử lý, lỗi hoặc metadata không hợp lệ sẽ không được đưa vào Excel. STT được đánh lại liên tục.</p>
      {selection.drafts.length > 0 && <p>{selection.drafts.length} bản nháp còn trường thiếu hoặc cần kiểm tra; các giá trị chưa xác định vẫn để trống.</p>}
      {selection.unclassified.length > 0 && <p className="metadata-errors">{selection.unclassified.length} tài liệu chưa phân loại chế độ sử dụng. Backend lưu trữ có thể mặc định mã rỗng thành 01 · Công khai. Excel vẫn giữ mã rỗng.</p>}
    </ConfirmDialog>}
  </section>;
}

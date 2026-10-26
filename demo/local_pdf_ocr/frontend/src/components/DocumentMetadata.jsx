import {useState} from "react";
import {Check, ChevronDown, Copy, Download, FileSearch, ListChecks, RotateCcw, AlertTriangle} from "lucide-react";
import {Button} from "@/components/ui/button";
import {Badge} from "@/components/ui/badge";
import {Alert, AlertDescription} from "@/components/ui/alert";
import ConfirmDialog from "./ConfirmDialog.jsx";
import NumberCodeReview from "./NumberCodeReview.jsx";
import {CATALOGS, FIELD_GROUPS, FIELD_KEYS, FIELD_LABELS, READ_ONLY, STATUS_LABELS,
  serializeDocumentFields, validateDocumentDraft} from "@/lib/documentFields.js";

export default function DocumentMetadata({draft, onEdit, onConfirmField, onReset, onExport, result, sourceFile, disabled = false}) {
  const [checked, setChecked] = useState(false);
  const [pendingExport, setPendingExport] = useState(null);
  const [message, setMessage] = useState("");
  const [exportError, setExportError] = useState("");
  const validation = validateDocumentDraft(draft);
  const recognized = FIELD_KEYS.filter(key => draft.fields[key].value && draft.fields[key].evidence.some(source => source.page || source.source === "source_page_count")).length;
  const confirmed = FIELD_KEYS.filter(key => draft.fields[key].status === "confirmed").length;

  async function performExport(kind) {
    setExportError("");
    try {
      const json = serializeDocumentFields(draft);
      if (kind === "copy") {await navigator.clipboard.writeText(json); setMessage("Đã sao chép JSON 22 trường.");}
      else {onExport(json); setMessage("Đã xuất bản nháp JSON 22 trường.");}
    } catch (error) {setExportError(error?.message || "Không thể xuất JSON. Vui lòng kiểm tra lại các trường.");}
  }
  function requestExport(kind) {
    setChecked(true); setMessage(""); setExportError("");
    if (Object.keys(validation.errors).length) {setExportError("Sửa các trường không hợp lệ trước khi xuất JSON."); return;}
    if (validation.missing.length || validation.review.length) setPendingExport(kind);
    else performExport(kind);
  }

  return <section className="document-metadata" aria-label="Thông tin văn bản 22 trường">
    <div className="metadata-summary"><strong>Tự động trích xuất: {recognized}/22 trường</strong><span>Đã xác nhận: {confirmed} · Cần kiểm tra: {validation.review.length}</span>
      <p>Số trường có bằng chứng, không phải độ chính xác OCR.</p></div>
    <div className="metadata-actions">
      <Button size="sm" title="Xuất JSON 22 trường" onClick={() => requestExport("download")}><Download/> Xuất JSON 22 trường</Button>
      <Button variant="outline" size="sm" onClick={() => requestExport("copy")}><Copy/> Sao chép JSON</Button>
      <Button variant="ghost" size="sm" onClick={() => {setChecked(true); setMessage(`Còn ${validation.missing.length} trường chưa xác định; ${validation.review.length} trường cần kiểm tra.`);}}><ListChecks/> Kiểm tra trường thiếu</Button>
      <Button variant="ghost" size="sm" onClick={onReset}><RotateCcw/> Khôi phục giá trị tự động</Button>
    </div>
    {validation.unclassifiedMode && <Alert className="metadata-warning"><AlertTriangle/><AlertDescription>Chưa phân loại chế độ sử dụng. Hệ thống lưu trữ có thể mặc định “Công khai” khi mã rỗng. JSON xuất vẫn giữ giá trị rỗng; hãy kiểm tra trước khi chuyển dữ liệu.</AlertDescription></Alert>}
    {message && <p className="metadata-message" role="status">{message}</p>}
    {exportError && <p className="metadata-errors" role="alert">{exportError}</p>}
    {checked && validation.missing.length > 0 && <p className="missing-fields">Chưa xác định: {validation.missing.map(key => FIELD_LABELS[key]).join("; ")}. Mã tài liệu luôn để trống theo schema.</p>}
    {FIELD_GROUPS.map((group, index) => <details className="metadata-group" key={group.title} open={index === 0 || checked}>
      <summary><span>{group.title}</span><span className="group-count">{group.keys.filter(key => draft.fields[key].value).length}/{group.keys.length}</span><ChevronDown size={15}/></summary>
      <div className="metadata-fields">
        {group.keys.map(key => {
          const entry = draft.fields[key];
          const invalid = checked && validation.errors[key];
          const controlProps = {id: `metadata-${key}`, name: key, value: entry.value,
            onChange: event => {onEdit(key, event.target.value); setMessage("");},
            "aria-invalid": Boolean(invalid), "aria-describedby": `metadata-${key}-help`};
          return <div className={"metadata-field " + (["subject","organName","description"].includes(key) ? "wide-field" : "")} key={key}>
            <div className="field-heading"><label htmlFor={controlProps.id}>{FIELD_LABELS[key]}</label>
              <Badge variant="outline" className={"field-status " + entry.status}>{STATUS_LABELS[entry.status]}</Badge>
              {!READ_ONLY.has(key) && entry.value && entry.status !== "confirmed" && <button type="button" className="confirm-field" title={`Xác nhận ${FIELD_LABELS[key]}`} aria-label={`Xác nhận ${FIELD_LABELS[key]}`} onClick={() => onConfirmField(key)}><Check size={13}/></button>}
            </div>
            {CATALOGS[key] ? <select {...controlProps}><option value="">Chưa xác định</option>{Object.entries(CATALOGS[key]).sort(([a],[b]) => a.localeCompare(b)).map(([code,label]) => <option value={code} key={code}>{code} · {label}</option>)}</select>
              : ["subject","description","autograph"].includes(key) ? <textarea {...controlProps} rows={key === "subject" ? 3 : 2} placeholder="Chưa xác định"/>
                : <input {...controlProps} type="text" readOnly={READ_ONLY.has(key)} placeholder={key === "docId" ? "Luôn để trống" : "Chưa xác định"}/>}
            <div id={`metadata-${key}-help`} className="field-help">
              {invalid ? <p className="metadata-errors">{invalid}</p> : entry.note ? <p>{entry.note}</p> : key === "issuedDate" ? <p>Định dạng DD-MM-YYYY.</p> : null}
              {entry.evidence.length > 0 && <details className="field-evidence"><summary><FileSearch size={12}/> {entry.evidence[0].page ? `Nguồn: trang ${entry.evidence[0].page}, dòng ${entry.evidence[0].line}` : "Nguồn: dữ liệu nguồn / quy tắc nghiệp vụ"}</summary>
                {entry.evidence.map((source, i) => <blockquote key={i}>{source.page && <span>Trang {source.page}, dòng {source.line}{source.precision === "block" ? " · vị trí theo khối" : ""}</span>}{source.text}</blockquote>)}
              </details>}
            </div>
            {key === "arcDocCode" && <NumberCodeReview result={result} sourceFile={sourceFile} disabled={disabled}/>}
          </div>;
        })}
      </div>
    </details>)}
    {pendingExport && <ConfirmDialog title="Xuất bản nháp cần kiểm tra" confirmLabel={pendingExport === "copy" ? "Sao chép bản nháp" : "Xuất bản nháp"}
      onCancel={() => setPendingExport(null)} onConfirm={() => {const kind = pendingExport; setPendingExport(null); performExport(kind);}}>
      <p>Còn {validation.missing.length} trường chưa xác định và {validation.review.length} trường cần kiểm tra. Các giá trị chưa xác định sẽ được giữ rỗng.</p>
      {validation.unclassifiedMode && <p className="metadata-errors"><strong>Chế độ sử dụng chưa được phân loại.</strong> Backend lưu trữ có thể mặc định mã rỗng thành 01 · Công khai. Hãy xác nhận rủi ro này trước khi xuất/chuyển dữ liệu.</p>}
      <p>Mức độ tin cậy là mã nghiệp vụ theo màu con dấu, không phải xác suất OCR.</p>
    </ConfirmDialog>}
  </section>;
}

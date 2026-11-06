import {useState} from "react";
import {Check, ChevronDown, Copy, Download, FileSearch, ListChecks, RotateCcw, AlertTriangle} from "lucide-react";
import {Button} from "@/components/ui/button";
import {Badge} from "@/components/ui/badge";
import {Alert, AlertDescription} from "@/components/ui/alert";
import ConfirmDialog from "./ConfirmDialog.jsx";
import NumberCodeReview from "./NumberCodeReview.jsx";
import Select from "@/components/ui/select.jsx";
import {CATALOGS, FIELD_GROUPS, FIELD_KEYS, FIELD_LABELS, READ_ONLY, STATUS_LABELS,
  serializeDocumentFields, validateDocumentDraft} from "@/lib/documentFields.js";

// Notes every OCR field or every confirmed field carries. They are stated once above the form (or by the
// status badge) and kept in the badge tooltip, instead of being repeated under each field.
const ROUTINE_NOTES = [
  "Nguồn OCR: đối chiếu bản gốc trước khi xác nhận; không tự sửa chữ hoặc dấu.",
  "Kết quả header một phần: đối chiếu trích yếu với ảnh nguồn, nhất là vùng dấu đóng chồng hoặc dòng bị cắt.",
  "Luôn để trống theo schema nghiệp vụ; không tự sinh mã.",
  "Đã chỉnh sửa thủ công; nguồn tự động chỉ để đối chiếu.",
  "Đã được người dùng kiểm tra và xác nhận.",
  "Tính từ mã văn bản đã được người dùng xác nhận.",
];
export function visibleNote(note = "") {
  return ROUTINE_NOTES.reduce((text, routine) => text.replace(routine, ""), note).replace(/\s+/gu, " ").trim();
}
// Business-code notes are explanations, not warnings: tooltip only.
const TOOLTIP_ONLY = new Set(["confidenceLevel", "isCan"]);

function evidenceLabel(source) {
  return source.page ? `trang ${source.page}, dòng ${source.line}` : "quy tắc nghiệp vụ";
}

export default function DocumentMetadata({draft, onEdit, onConfirmField, onReset, onExport, result, sourceFile, disabled = false}) {
  const [checked, setChecked] = useState(false);
  const [pendingExport, setPendingExport] = useState(null);
  const [message, setMessage] = useState("");
  const [exportError, setExportError] = useState("");
  const validation = validateDocumentDraft(draft);
  const recognized = FIELD_KEYS.filter(key => draft.fields[key].value && draft.fields[key].evidence.some(source => source.page || source.source === "source_page_count")).length;
  const confirmed = FIELD_KEYS.filter(key => draft.fields[key].status === "confirmed").length;
  const fromOcr = Boolean(result?.used_ocr);

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
    <div className="metadata-toolbar">
      <div className="metadata-summary" title="Số trường có bằng chứng, không phải độ chính xác OCR.">
        <strong>{recognized}/22 trường tự động</strong>
        <span className={validation.review.length ? "summary-review" : ""}>{validation.review.length} cần kiểm tra</span>
        <span>{confirmed} đã xác nhận</span>
      </div>
      <div className="metadata-actions">
        <Button size="sm" title="Xuất JSON 22 trường" aria-label="Xuất JSON 22 trường" onClick={() => requestExport("download")}><Download/> Xuất JSON</Button>
        <Button variant="outline" size="icon" title="Sao chép JSON" aria-label="Sao chép JSON" onClick={() => requestExport("copy")}><Copy/></Button>
        <Button variant="ghost" size="icon" title="Kiểm tra trường thiếu" aria-label="Kiểm tra trường thiếu"
          onClick={() => {setChecked(true); setMessage(`Còn ${validation.missing.length} trường chưa xác định; ${validation.review.length} trường cần kiểm tra.`);}}><ListChecks/></Button>
        <Button variant="ghost" size="icon" title="Khôi phục giá trị tự động" aria-label="Khôi phục giá trị tự động" onClick={onReset}><RotateCcw/></Button>
      </div>
    </div>
    <p className="metadata-hint">
      {fromOcr ? "Giá trị từ OCR: đối chiếu bản gốc rồi bấm ✓ để xác nhận. Ứng dụng không tự sửa chữ hay dấu." : "Đối chiếu bản gốc rồi bấm ✓ để xác nhận."}
    </p>
    {draft.typeLabel && !draft.fields.typeName.value && <p className="detected-document-type">Loại nhận diện: <strong>{draft.typeLabel}</strong> · chưa có mã nghiệp vụ, hãy chọn ở “Loại tài liệu”.</p>}
    {validation.unclassifiedMode && checked && <Alert className="metadata-warning"><AlertTriangle/><AlertDescription>Chưa phân loại chế độ sử dụng. Hệ thống lưu trữ có thể mặc định “Công khai” khi mã rỗng; JSON vẫn giữ giá trị rỗng.</AlertDescription></Alert>}
    {message && <p className="metadata-message" role="status">{message}</p>}
    {exportError && <p className="metadata-errors" role="alert">{exportError}</p>}
    {checked && validation.missing.length > 0 && <p className="missing-fields">Chưa xác định: {validation.missing.map(key => FIELD_LABELS[key]).join("; ")}. Mã tài liệu luôn để trống theo schema.</p>}
    {FIELD_GROUPS.map((group, index) => <details className="metadata-group" key={group.title} open={index === 0 || checked}>
      <summary><span>{group.title}</span><span className="group-count">{group.keys.filter(key => draft.fields[key].value).length}/{group.keys.length}</span><ChevronDown size={15}/></summary>
      <div className="metadata-fields">
        {group.keys.map(key => {
          const entry = draft.fields[key];
          const invalid = checked && validation.errors[key];
          // The detected type line above already explains a missing type code.
          const note = TOOLTIP_ONLY.has(key) || (key === "typeName" && draft.typeLabel) ? "" : visibleNote(entry.note);
          // Read-only fields follow Mã văn bản / the source and cannot be confirmed on their own: no badge.
          const showStatus = !READ_ONLY.has(key) && (entry.status === "review" || entry.status === "confirmed");
          const edit = value => {onEdit(key, value); setMessage("");};
          const controlProps = {id: `metadata-${key}`, name: key, value: entry.value,
            onChange: event => edit(event.target.value),
            "aria-invalid": Boolean(invalid), "aria-describedby": `metadata-${key}-help`, title: entry.note || undefined};
          return <div className={`metadata-field status-${entry.status}` + (["subject","organName","description"].includes(key) ? " wide-field" : "")} key={key}>
            <div className="field-heading"><label htmlFor={controlProps.id}>{FIELD_LABELS[key]}</label>
              {showStatus && <Badge variant="outline" className={"field-status " + entry.status} title={entry.note || undefined}>{STATUS_LABELS[entry.status]}</Badge>}
              {!READ_ONLY.has(key) && entry.value && entry.status !== "confirmed" && <button type="button" className="confirm-field" title={`Xác nhận ${FIELD_LABELS[key]}`} aria-label={`Xác nhận ${FIELD_LABELS[key]}`} onClick={() => onConfirmField(key)}><Check size={13}/></button>}
              {entry.evidence.length > 0 && <details className="field-evidence"><summary title="Xem dòng nguồn"><FileSearch size={11}/> {evidenceLabel(entry.evidence[0])}</summary>
                <div className="field-evidence-popover">{entry.evidence.map((source, i) => <blockquote key={i}>{source.page && <span>Trang {source.page}, dòng {source.line}{source.precision === "block" ? " · vị trí theo khối" : ""}</span>}{source.text}</blockquote>)}</div>
              </details>}
            </div>
            {CATALOGS[key] ? <Select {...controlProps} onChange={edit} popupMinWidth={180} options={[{value:"",label:"Chưa xác định"},
              ...Object.entries(CATALOGS[key]).sort(([a],[b]) => a.localeCompare(b)).map(([code,label]) => ({value:code,label:`${code} · ${label}`}))]}/>
              : ["subject","description","autograph"].includes(key) ? <textarea {...controlProps} rows={key === "subject" ? 3 : 2} placeholder="Chưa xác định"/>
                : <input {...controlProps} type="text" readOnly={READ_ONLY.has(key)} placeholder={key === "docId" ? "Luôn để trống" : key === "issuedDate" ? "DD-MM-YYYY" : "Chưa xác định"}/>}
            {(invalid || note || entry.candidate) && <div id={`metadata-${key}-help`} className="field-help">
              {invalid ? <p className="metadata-errors">{invalid}</p> : note ? <p className="field-note">{note}</p> : null}
              {entry.candidate && <details className="metadata-unverified-candidate"><summary>Ứng viên chưa xác minh — dấu đóng chồng</summary>
                <p>Chỉ để đối chiếu ảnh nguồn. Nội dung này không tự điền hoặc xuất thành trích yếu.</p><blockquote>{entry.candidate}</blockquote></details>}
            </div>}
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

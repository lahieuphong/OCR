import {useEffect, useRef, useState} from "react";
import {
  ScanText, FileText, FileImage, UploadCloud, ShieldCheck, ArrowRight,
  Download, Copy, Check, AlertTriangle, LoaderCircle, Clock3, FileJson,
  ScanLine, CircleCheck, ChevronLeft, ChevronRight, RefreshCw, LockKeyhole,
} from "lucide-react";
import {Button} from "@/components/ui/button";
import {Card, CardHeader, CardTitle, CardDescription, CardContent} from "@/components/ui/card";
import {Badge} from "@/components/ui/badge";
import {Tabs, TabsList, TabsTrigger, TabsContent} from "@/components/ui/tabs";
import {Alert, AlertTitle, AlertDescription} from "@/components/ui/alert";
import {Tooltip, TooltipContent, TooltipProvider, TooltipTrigger} from "@/components/ui/tooltip";
import {Separator} from "@/components/ui/separator";
import {Progress} from "@/components/ui/progress";
import DocumentMetadata from "@/components/DocumentMetadata.jsx";
import ConfirmDialog from "@/components/ConfirmDialog.jsx";
import DocumentList from "@/components/DocumentList.jsx";
import useDocumentBatch from "@/hooks/useDocumentBatch.js";
import {batchDocumentStatus, BATCH_STATUS_LABELS} from "@/lib/documentBatch.js";
import {EXCEL_FILENAME} from "@/lib/excelExport.js";
import {editDocumentField, confirmDocumentField} from "@/lib/documentFields.js";

function formatTime(ms) {
  if (!Number.isFinite(ms)) return "—";
  return ms >= 60000 ? (ms / 60000).toFixed(1) + " phút" : (ms / 1000).toFixed(1) + " giây";
}
function downloadText(name, content, type = "text/plain;charset=utf-8") {
  const url = URL.createObjectURL(new Blob([content], {type}));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1200);
}
function shortName(name) {
  return (name || "ocr-result").replace(/\.[^.]+$/, "").replace(/[\\/:*?"<>|]/g, "_");
}

function ActionButton({title, disabled, onClick, children}) {
  return <Tooltip>
    <TooltipTrigger asChild>
      <span className="action-wrap" tabIndex={disabled ? 0 : undefined} aria-label={disabled ? title : undefined}>
        <Button variant="outline" size="icon" title={title} aria-label={title} disabled={disabled} onClick={onClick}>{children}</Button>
      </span>
    </TooltipTrigger>
    <TooltipContent>{title}</TooltipContent>
  </Tooltip>;
}

function EmptyResult({working, documentSelected, nativeText}) {
  return <div className="result-placeholder">
    <span className={"result-icon " + (working ? "active-icon" : "")}>
      {working ? <LoaderCircle className="spin" size={30}/> : <ScanText size={30} strokeWidth={1.5}/>}
    </span>
    <h3>{working ? "Đang bóc tách văn bản" : "Văn bản sẽ xuất hiện tại đây"}</h3>
    <p>{working
      ? nativeText ? "Đang trích xuất văn bản có sẵn trong PDF." : "Đang nhận dạng văn bản từ các trang tài liệu."
      : documentSelected ? "Chọn phương pháp, sau đó nhấn “Bóc tách văn bản” để bắt đầu." : "Chọn một tài liệu ở bên trái để bắt đầu."}</p>
    {!working && <span className="empty-result-note"><FileText size={14}/> Toàn văn, theo trang và xuất kết quả</span>}
  </div>;
}

export default function App() {
  const fileInput = useRef(null);
  const pickerIntent = useRef("add");
  const [hoverUpload, setHoverUpload] = useState(false);
  const [page, setPage] = useState(1);
  const [copied, setCopied] = useState(false);
  const [health, setHealth] = useState("checking");
  const [healthAttempt, setHealthAttempt] = useState(0);
  const {documents,activeId,document,preview,selectedMode,resultsByMode,metadataByMode,setMetadataByMode,
    pendingDiscard,setPendingDiscard,working,elapsed,error,setError,activeView,setActiveView,canRun,canRunBatch,
    batchProgress,chooseFiles,selectDocument,removeDocument,changeMode,restoreMetadata,runOcr,runBatch,confirmDocument,setIncluded} = useDocumentBatch(health);

  useEffect(() => {
    let cancelled = false;
    setHealth("checking");
    fetch("/api/health").then(async response => {
      if (!response.ok) throw Error("unhealthy");
      return response.json();
    }).then(data => {
      if (!cancelled) setHealth(data.state === "ready_to_initialize" ? "connected" : "not-ready");
    }).catch(() => {if (!cancelled) setHealth("disconnected");});
    return () => {cancelled = true;};
  }, [healthAttempt]);
  useEffect(() => {setPage(1); setCopied(false);}, [activeId,selectedMode]);
  const result = resultsByMode[selectedMode] || null;
  const currentPage = result?.pages.find(x => x.page === page);
  const shownText = activeView === "page" ? (currentPage?.text || "") : (result?.text || "");
  const isPDF = document && /\.pdf$/i.test(document.name);
  const FileIcon = isPDF ? FileText : FileImage;
  const comparisonResult = selectedMode === "hybrid_h1" ? resultsByMode.hybrid_h1 : resultsByMode.native_text;
  const comparisonOcr = selectedMode === "hybrid_h1" ? comparisonResult?.ocr_result : resultsByMode.vietocr_ocr;
  const bothReady = Boolean(isPDF && comparisonResult && comparisonOcr);
  const stateLabel = working ? "Đang bóc tách" : error ? "Cần kiểm tra" : result ? "Hoàn tất" : document ? "Đã chọn tài liệu" : "Chưa chọn tài liệu";

  async function copyText() {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(shownText);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setError("Không thể sao chép bằng Clipboard. Hãy chọn văn bản thủ công.");
    }
  }

  return <TooltipProvider delayDuration={250}>
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark"><ScanText size={25} strokeWidth={1.7}/></span>
          <div><h1>VietDoc OCR</h1><p>Bóc tách văn bản hành chính</p></div>
        </div>
        <div className="topbar-right">
          <span className="local-label"><LockKeyhole size={14}/> Xử lý trên máy</span>
          <Badge variant="outline" className={"server-pill " + health} role="status">
            <span className="server-dot"/>
            {health === "connected" ? "Hệ thống sẵn sàng" : health === "checking" ? "Đang kết nối" : health === "not-ready" ? "Thiếu model OCR" : "Chưa kết nối"}
          </Badge>
        </div>
      </header>

      <main className="main-container">
        {health === "disconnected" && <Alert className="connection-alert">
          <AlertTriangle size={17}/><AlertTitle>Máy chủ xử lý chưa sẵn sàng</AlertTitle>
          <AlertDescription>Kiểm tra cửa sổ trạng thái ứng dụng và thử kết nối lại.
            <Button variant="outline" size="sm" onClick={() => setHealthAttempt(value => value + 1)}><RefreshCw size={14}/> Kết nối lại</Button>
          </AlertDescription>
        </Alert>}

        <section className="workspace" aria-label="Không gian bóc tách văn bản">
          <Card className="left-pane">
            <CardHeader className="pane-header">
              <span className="pane-number">1</span>
              <div><CardTitle>Tài liệu đầu vào</CardTitle><CardDescription>Chọn tài liệu và phương pháp xử lý</CardDescription></div>
            </CardHeader>
            <Separator/>
            <CardContent className="input-content">
              <div className={"dropzone " + (hoverUpload ? "drag-over " : "") + (document ? "has-file" : "")}
                onDragOver={event => {event.preventDefault(); if (!working) setHoverUpload(true);}}
                onDragLeave={event => {if (!event.currentTarget.contains(event.relatedTarget)) setHoverUpload(false);}}
                onDrop={event => {event.preventDefault(); setHoverUpload(false); chooseFiles(event.dataTransfer.files);}}>
                <input ref={fileInput} type="file" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
                  aria-label="Chọn tài liệu PDF hoặc ảnh" multiple disabled={working} hidden
                  onChange={event => {chooseFiles(event.target.files, {replaceActive:pickerIntent.current === "replace"}); pickerIntent.current = "add"; event.target.value = "";}}/>
                {document ? <div className="selected-file">
                  <span className="selected-file-icon"><FileIcon size={23}/></span>
                  <div className="selected-file-info"><strong title={document.name}>{document.name}</strong>
                    <small>{(document.size / (1024 * 1024)).toFixed(2)} MB · {isPDF ? "Tài liệu PDF" : "Hình ảnh"}</small></div>
                  <Button variant="outline" size="sm" disabled={working} onClick={() => {pickerIntent.current = "replace"; fileInput.current?.click();}}>Đổi tệp</Button>
                </div> : <div className="drop-empty">
                  <UploadCloud size={25} strokeWidth={1.6}/>
                  <div><h3>Kéo thả tài liệu vào đây</h3><p>PDF, PNG, JPG/JPEG</p></div>
                  <Button size="sm" onClick={() => {pickerIntent.current = "add"; fileInput.current?.click();}}>Chọn tài liệu</Button>
                </div>}
                <p className="file-limits">Tối đa 15 MB · PDF tối đa 6 trang · Ảnh tối đa 12 MP</p>
              </div>

              {documents.length > 0 && <div className="input-queue">
                <div className="queue-heading"><span>Đã chọn {documents.length} tài liệu</span><Button size="sm" variant="outline" disabled={working} onClick={() => {pickerIntent.current = "add"; fileInput.current?.click();}}>Thêm tài liệu</Button></div>
                <ol>{documents.map((doc,index) => <li key={doc.id} className={doc.id === activeId ? "active" : ""}>
                  <button className="select-queued-file" onClick={() => selectDocument(doc.id)} title={doc.name}>{index+1}. {doc.name}<small>{BATCH_STATUS_LABELS[batchDocumentStatus(doc)]}</small></button>
                  <select aria-label={`Phương pháp tài liệu ${index+1}`} value={doc.mode} disabled={working} onChange={event => changeMode(event.target.value,doc.id)}>
                    {/\.pdf$/iu.test(doc.name) && <option value="native_text">Văn bản có sẵn</option>}<option value="vietocr_ocr">Nhận dạng OCR</option>
                    {/\.pdf$/iu.test(doc.name) && <option value="hybrid_h1">Kết hợp PDF + OCR (thử nghiệm)</option>}
                  </select>
                  <button className="remove-document" aria-label={`Xóa tài liệu ${index+1}: ${doc.name}`} disabled={working} onClick={() => removeDocument(doc.id)}>×</button>
                </li>)}</ol>
              </div>}

              <div className="preview-area">
                <div className="section-label"><span>Xem trước tài liệu</span>{preview && <span>{isPDF ? "PDF" : "Ảnh"}</span>}</div>
                {preview ? isPDF
                  ? <iframe className="pdf-view" src={preview + "#toolbar=0"} title="Bản xem trước PDF"/>
                  : <div className="image-view"><img src={preview} alt="Bản xem trước tài liệu"/></div>
                  : <div className="preview-placeholder"><FileText size={32} strokeWidth={1.3}/><span>Chưa có tài liệu để xem trước</span></div>}
              </div>

              <fieldset className="ocr-mode-selector" disabled={!document || working}>
                <legend>Phương pháp xử lý</legend>
                <label className={"mode-option " + (selectedMode === "native_text" ? "selected" : "") + (!isPDF ? " unavailable" : "")}>
                  <input type="radio" name="mode" value="native_text" checked={selectedMode === "native_text"}
                    onChange={() => changeMode("native_text")} disabled={!isPDF || working}/>
                  <FileText size={18}/><span className="mode-copy"><span className="mode-name">Trích xuất văn bản có sẵn</span><small>Dành cho PDF có thể chọn và sao chép chữ</small></span>
                  {resultsByMode.native_text && <Check className="mode-done" size={16} aria-label="Đã có kết quả"/>}
                </label>
                <label className={"mode-option " + (selectedMode === "vietocr_ocr" ? "selected" : "")}>
                  <input type="radio" name="mode" value="vietocr_ocr" checked={selectedMode === "vietocr_ocr"}
                    onChange={() => changeMode("vietocr_ocr")} disabled={working}/>
                  <ScanLine size={18}/><span className="mode-copy"><span className="mode-name">Nhận dạng văn bản từ ảnh/PDF</span><small>Dành cho ảnh chụp và tài liệu scan</small></span>
                  {resultsByMode.vietocr_ocr && <Check className="mode-done" size={16} aria-label="Đã có kết quả"/>}
                </label>
                {isPDF && <label className={"mode-option " + (selectedMode === "hybrid_h1" ? "selected" : "")}>
                  <input type="radio" name="mode" value="hybrid_h1" checked={selectedMode === "hybrid_h1"}
                    onChange={() => changeMode("hybrid_h1")} disabled={working}/>
                  <ScanText size={18}/><span className="mode-copy"><span className="mode-name">Kết hợp PDF + OCR (thử nghiệm)</span><small>Chọn nguồn chữ theo từng dòng; cần đối chiếu kết quả</small></span>
                  {resultsByMode.hybrid_h1 && <Check className="mode-done" size={16} aria-label="Đã có kết quả"/>}
                </label>}
              </fieldset>
              <p className="mode-note">{selectedMode === "native_text" ? "Đọc lớp chữ có sẵn trong PDF; không tự chuyển sang OCR."
                : selectedMode === "hybrid_h1" ? "Thử nghiệm: dùng chữ có sẵn khi đủ điều kiện; dòng còn lại giữ OCR. Đối chiếu trước khi xuất dữ liệu."
                : "Nhận dạng trực tiếp từ hình ảnh; giữ nguyên kết quả nhận dạng."}</p>

              {health === "not-ready" && <Alert className="model-alert">
                <AlertTriangle size={16}/><AlertTitle>OCR chưa sẵn sàng</AlertTitle>
                <AlertDescription>Thiếu model hoặc model chưa hợp lệ. Bạn vẫn có thể trích xuất văn bản có sẵn trong PDF.</AlertDescription>
              </Alert>}

              <div className="input-actions">
              <Button className="run-button" size="lg" onClick={() => runOcr()} disabled={!document || working || !canRun}>
                {working ? <LoaderCircle className="spin" size={18}/> : <ScanText size={18}/>}
                {working ? "Đang bóc tách…" : "Bóc tách văn bản"}{!working && <ArrowRight size={17}/>}
              </Button>
              {documents.length > 1 && <Button className="batch-run-button" variant="outline" onClick={runBatch} disabled={working || !canRunBatch}>Bóc tách tất cả tài liệu chưa xử lý</Button>}
              {batchProgress && documents.length > 1 && <p className="queue-progress" role="status">Đã xử lý {batchProgress.completed}/{batchProgress.total} tài liệu trong lượt này</p>}
              {working && <div className="processing-status" role="status"><Progress value={null} className="processing-progress" aria-label="Đang xử lý, chưa có tiến độ phần trăm"/><span><Clock3 size={14}/> Đang xử lý trên máy · {elapsed.toFixed(0)} giây</span></div>}
              {error && <Alert variant="destructive" className="error-box"><AlertTriangle size={17}/><AlertTitle>Không thể hoàn tất thao tác</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>}
              </div>
            </CardContent>
          </Card>

          <Card className="right-pane" aria-busy={working}>
            <CardHeader className="pane-header">
              <span className="pane-number">2</span>
              <div><CardTitle>Kết quả bóc tách</CardTitle><CardDescription>Đọc, sao chép hoặc lưu văn bản</CardDescription></div>
              <Badge variant="outline" className={"document-state " + (result ? "complete" : "")} role="status">
                {result && <CircleCheck size={12}/>}{stateLabel}
              </Badge>
            </CardHeader>
            <Separator/>
            <Tabs className="result-tabs" value={activeView} onValueChange={value => {setActiveView(value); setCopied(false);}}>
              <div className="result-toolbar">
                <TabsList aria-label="Cách xem kết quả">
                  <TabsTrigger value="list">Danh sách văn bản</TabsTrigger>
                  <TabsTrigger value="metadata" disabled={!result}>Thông tin văn bản</TabsTrigger>
                  <TabsTrigger value="text">Toàn văn</TabsTrigger>
                  <TabsTrigger value="page">Theo trang</TabsTrigger>
                  {bothReady && <TabsTrigger value="compare">So sánh</TabsTrigger>}
                </TabsList>
              <div className="toolbar-actions">
                <ActionButton title="Sao chép văn bản" disabled={!result} onClick={copyText}>{copied ? <Check size={16}/> : <Copy size={16}/>}</ActionButton>
                <ActionButton title="Tải TXT" disabled={!result} onClick={() => downloadText(shortName(document.name) + "_" + result.method + ".txt", result.text)}><Download size={16}/></ActionButton>
                <ActionButton title="Tải báo cáo JSON" disabled={!result} onClick={() => downloadText(shortName(document.name) + "_" + result.method + ".json", JSON.stringify(result, null, 2), "application/json;charset=utf-8")}><FileJson size={16}/></ActionButton>
              </div>
            </div>
            {copied && <span className="copy-feedback" role="status"><Check size={14}/> Đã sao chép văn bản</span>}

            {result && <>
              <div className={"result-origin " + (result.used_ocr ? "ocr-origin" : "native-origin")}>
                <ShieldCheck size={14}/><span>{result.method === "hybrid_h1" ? "Kết hợp PDF + OCR · Thử nghiệm, cần đối chiếu"
                  : result.used_ocr ? "Nhận dạng từ ảnh · PaddleOCR + VietOCR B1024" : "Trích xuất văn bản có sẵn trong PDF · Không chạy OCR"}</span>
              </div>
              <div className="results-stats">
                <span><b>{result.page_count}</b> trang</span><span><b>{result.line_count}</b> dòng</span>
                <span><Clock3 size={14}/><b>{formatTime(result.elapsed_ms)}</b></span>
                {result.used_ocr && <span className={result.decoder_limit_hits > 0 ? "truncated-lines" : ""}><b>{result.decoder_limit_hits ?? "—"}</b> dòng bị cắt</span>}
                {result.method === "hybrid_h1" && <><span><b>{result.h1?.native_lines ?? 0}</b> dòng dùng chữ PDF</span><span><b>{result.h1?.ocr_lines ?? 0}</b> dòng giữ OCR</span></>}
              </div>
            </>}

            {result && activeView === "page" && <nav className="page-tabs" aria-label="Chọn trang kết quả">
              <Button variant="outline" size="icon" aria-label="Trang trước" disabled={page === result.pages[0]?.page} onClick={() => setPage(result.pages[result.pages.findIndex(item => item.page === page) - 1]?.page ?? page)}><ChevronLeft size={16}/></Button>
              {result.pages.map(item => <Button key={item.page} variant={page === item.page ? "default" : "ghost"} size="sm" aria-current={page === item.page ? "page" : undefined} onClick={() => {setPage(item.page); setCopied(false);}}>Trang {item.page}</Button>)}
              <Button variant="outline" size="icon" aria-label="Trang sau" disabled={page === result.pages.at(-1)?.page} onClick={() => setPage(result.pages[result.pages.findIndex(item => item.page === page) + 1]?.page ?? page)}><ChevronRight size={16}/></Button>
            </nav>}

            <TabsContent value={activeView} className={"text-output " + (!result && activeView !== "list" ? "empty-result" : "") + (activeView === "list" || result && activeView === "metadata" ? " metadata-output" : "")} aria-label="Nội dung văn bản">
              {activeView === "list" ? <DocumentList documents={documents} working={working} onSelect={selectDocument} onRetry={runOcr} onConfirm={confirmDocument} onIncluded={setIncluded}
                onDownload={bytes => downloadText(EXCEL_FILENAME,bytes,"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}/>
                : result && activeView === "metadata" && metadataByMode[selectedMode] ? <fieldset className="metadata-editing" disabled={working}><DocumentMetadata key={activeId + selectedMode} draft={metadataByMode[selectedMode]} result={result} sourceFile={document} disabled={working}
                onEdit={(key, value) => setMetadataByMode(previous => ({...previous, [selectedMode]: editDocumentField(previous[selectedMode], key, value)}))}
                onConfirmField={key => setMetadataByMode(previous => ({...previous, [selectedMode]: confirmDocumentField(previous[selectedMode], key)}))}
                onReset={restoreMetadata} onExport={json => downloadText(shortName(document.name) + "_" + selectedMode + "_metadata.json", json, "application/json;charset=utf-8")}/></fieldset>
                : result && activeView === "compare" && bothReady ? <div className="comparison-columns">
                <section><h3>{selectedMode === "hybrid_h1" ? "Kết hợp PDF + OCR (thử nghiệm)" : "Văn bản có sẵn trong PDF"}</h3><pre>{comparisonResult.text}</pre></section>
                <section><h3>Nhận dạng từ ảnh/PDF</h3><pre>{comparisonOcr.text}</pre></section>
              </div> : result ? <pre>{shownText || "Không phát hiện được dòng văn bản. Hãy kiểm tra ảnh/PDF gốc."}</pre>
                : <EmptyResult working={working} documentSelected={Boolean(document)} nativeText={selectedMode === "native_text"}/>}
            </TabsContent>
            </Tabs>
            <div className="output-bottom"><ShieldCheck size={14}/><span>Giữ nguyên nội dung và dấu tiếng Việt</span><span className="output-format">TXT / JSON</span></div>
          </Card>
        </section>
        <footer className="footer"><span><LockKeyhole size={13}/> Tài liệu được xử lý trên máy tính của bạn</span><span>Bản thử nghiệm nội bộ</span></footer>
      </main>
      {pendingDiscard && <ConfirmDialog title={pendingDiscard.title || "Giữ hay thay thế chỉnh sửa?"} confirmLabel={pendingDiscard.confirmLabel || "Thay thế bản nháp"} onCancel={() => setPendingDiscard(null)}
        onConfirm={() => {const action = pendingDiscard.run; setPendingDiscard(null); action();}}><p>{pendingDiscard.message}</p></ConfirmDialog>}
    </div>
  </TooltipProvider>;
}

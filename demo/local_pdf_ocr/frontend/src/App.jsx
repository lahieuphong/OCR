import {useEffect, useRef, useState} from "react";
import {
  ScanText, FileText, FileImage, UploadCloud, ShieldCheck, ArrowRight,
  Download, Copy, Check, AlertTriangle, LoaderCircle, Clock3, FileJson,
  CircleCheck, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, RefreshCw, LockKeyhole, FolderOpen, Pause, RotateCcw, ListChecks,
} from "lucide-react";
import {Button} from "@/components/ui/button";
import {Card} from "@/components/ui/card";
import {Badge} from "@/components/ui/badge";
import {Tabs, TabsList, TabsTrigger, TabsContent} from "@/components/ui/tabs";
import {Alert, AlertTitle, AlertDescription} from "@/components/ui/alert";
import {Tooltip, TooltipContent, TooltipProvider, TooltipTrigger} from "@/components/ui/tooltip";
import {Progress} from "@/components/ui/progress";
import DocumentMetadata from "@/components/DocumentMetadata.jsx";
import ConfirmDialog from "@/components/ConfirmDialog.jsx";
import AppMenu, {useWindowTitleBar} from "@/components/AppMenu.jsx";
import DocumentList from "@/components/DocumentList.jsx";
import DocumentNavigator from "@/components/DocumentNavigator.jsx";
import DocumentPreview from "@/components/DocumentPreview.jsx";
import DocumentQueue from "@/components/DocumentQueue.jsx";
import useDocumentBatch from "@/hooks/useDocumentBatch.js";
import {EXCEL_FILENAME} from "@/lib/excelExport.js";
import {editDocumentField, confirmDocumentField} from "@/lib/documentFields.js";
import {FAST_MODE_DESCRIPTION, RERUN_ONE_LABEL, RERUN_THIS_LABEL, RESUME_LABEL, RUN_ONE_FAST_LABEL, partialScope, rerunAllLabel, resultTextExport, resumeLabel, runAllLabel} from "@/lib/processingModes.js";
import {dropHasFolder, filesFromDrop} from "@/lib/folderImport.js";

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
function remainingText(ms) {
  if (!Number.isFinite(ms)) return "";
  const minutes = Math.ceil(ms / 60000);
  return minutes <= 1 ? " · còn khoảng 1 phút" : minutes < 60 ? ` · còn khoảng ${minutes} phút`
    : ` · còn khoảng ${Math.floor(minutes / 60)} giờ ${minutes % 60} phút`;
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

function EmptyResult({working, documentSelected}) {
  return <div className="result-placeholder">
    <span className={"result-icon " + (working ? "active-icon" : "")}>
      {working ? <LoaderCircle className="spin" size={30}/> : <ScanText size={30} strokeWidth={1.5}/>}
    </span>
    <h3>{working ? "Đang bóc tách văn bản" : "Văn bản sẽ xuất hiện tại đây"}</h3>
    <p>{working ? "Đang xét vùng header cần thiết; không OCR toàn bộ tài liệu."
      : documentSelected ? `Nhấn “${RUN_ONE_FAST_LABEL}” để bắt đầu.` : "Chọn một tài liệu ở bên trái để bắt đầu."}</p>
    {!working && <span className="empty-result-note"><FileText size={14}/> Header một phần và metadata 22 trường</span>}
  </div>;
}

export default function App() {
  const fileInput = useRef(null);
  const folderInput = useRef(null);
  const pickerIntent = useRef("add");
  const [hoverUpload, setHoverUpload] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(true);
  const [page, setPage] = useState(1);
  const [copied, setCopied] = useState(false);
  const [health, setHealth] = useState("checking");
  const [healthAttempt, setHealthAttempt] = useState(0);
  const windowTitleBar = useWindowTitleBar();
  const {documents,activeId,document,preview,selectedMode,resultsByMode,metadataByMode,setMetadataByMode,
    pendingDiscard,setPendingDiscard,working,elapsed,error,setError,activeView,setActiveView,canRun,canRunBatch,
    batchProgress,chooseFiles,selectDocument,removeDocument,restoreMetadata,runOcr,runBatch,confirmDocument,setIncluded,
    failedCount,canRunFailed,runFailed,pause,pausing,notice,dismissNotice,resumeCount,resume} = useDocumentBatch(health);
  function dropDocuments(dataTransfer) {
    // Plain files are added at once; a dropped folder is read (with subfolders) first.
    if (!dropHasFolder(dataTransfer)) {chooseFiles(dataTransfer.files); return;}
    filesFromDrop(dataTransfer).then(({files,fromFolder}) => chooseFiles(files,{fromFolder}))
      .catch(() => setError("Không đọc được thư mục đã kéo thả. Hãy dùng nút “Chọn thư mục”."));
  }

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
  // Every document is processed with the fast header mode (22 fields from page 1); the app offers no other method.
  const result = resultsByMode[selectedMode] || null;
  // The selected document already has a result: nothing is left to run, so the run button
  // steps back (a "done" line and a secondary "Bóc tách lại").
  const done = Boolean(result) && !working;
  const allDone = documents.length > 1 && documents.every(doc => doc.resultsByMode[doc.mode]);
  useEffect(() => {
    if (result?.pages?.length && !result.pages.some(item => item.page === page)) setPage(result.pages[0].page);
  }, [result,page]);
  const currentPage = result?.pages.find(x => x.page === page);
  const shownText = activeView === "page" ? (currentPage?.text || "") : (result?.text || "");
  const isPDF = document && /\.pdf$/i.test(document.name);
  const FileIcon = isPDF ? FileText : FileImage;
  const stateLabel = working ? "Đang bóc tách header" : error ? "Cần kiểm tra" : result ? "Header một phần" : document ? "Đã chọn tài liệu" : "Chưa chọn tài liệu";

  async function copyText() {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(resultTextExport(result, shownText));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setError("Không thể sao chép bằng Clipboard. Hãy chọn văn bản thủ công.");
    }
  }

  const openFiles = (intent = "add") => {pickerIntent.current = intent; fileInput.current?.click();};

  return <TooltipProvider delayDuration={250}>
    <div className={"app-shell" + (windowTitleBar ? " window-title-bar" : "")}>
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark"><ScanText size={22} strokeWidth={1.7}/></span>
          <div><h1>VietDoc OCR</h1><p>Bóc tách văn bản hành chính</p></div>
        </div>
        <div className="topbar-right">
          <span className="local-label"><LockKeyhole size={14}/> Xử lý trên máy</span>
          <Badge variant="outline" className={"server-pill " + health} role="status">
            <span className="server-dot"/>
            {health === "connected" ? "Hệ thống sẵn sàng" : health === "checking" ? "Đang kết nối" : health === "not-ready" ? "Thiếu model OCR" : "Chưa kết nối"}
          </Badge>
          <AppMenu/>
        </div>
      </header>

      <main className="main-container">
        {health === "disconnected" && <Alert className="connection-alert">
          <AlertTriangle size={17}/><AlertTitle>Máy chủ xử lý chưa sẵn sàng</AlertTitle>
          <AlertDescription>Kiểm tra cửa sổ trạng thái ứng dụng và thử kết nối lại.
            <Button variant="outline" size="sm" onClick={() => setHealthAttempt(value => value + 1)}><RefreshCw size={14}/> Kết nối lại</Button>
          </AlertDescription>
        </Alert>}

        {/* Fills the window: each column scrolls inside itself, the page does not (except on narrow windows). */}
        <section className="workspace" aria-label="Không gian bóc tách văn bản">
          <Card className="left-pane">
            <div className="pane-header">
              <span className="pane-number">1</span>
              <div className="pane-title"><h2>Tài liệu</h2>
                <p>{documents.length ? `${documents.length} tài liệu` : "PDF, PNG, JPG · tối đa 15 MB/tệp"}</p></div>
              {documents.length > 0 && <div className="pane-header-actions">
                <Button size="sm" variant="outline" disabled={working} onClick={() => openFiles("add")} title="Thêm tệp PDF/PNG/JPG"><UploadCloud size={14}/> Thêm tệp</Button>
                <Button size="sm" variant="outline" disabled={working} onClick={() => folderInput.current?.click()} title="Thêm cả thư mục (gồm thư mục con)"><FolderOpen size={14}/> Thư mục</Button>
              </div>}
            </div>

            <div className={"dropzone pane-body " + (hoverUpload ? "drag-over " : "") + (documents.length ? "has-file" : "is-empty")}
              onDragOver={event => {event.preventDefault(); if (!working) setHoverUpload(true);}}
              onDragLeave={event => {if (!event.currentTarget.contains(event.relatedTarget)) setHoverUpload(false);}}
              onDrop={event => {event.preventDefault(); setHoverUpload(false); if (!working) dropDocuments(event.dataTransfer);}}>
              <input ref={fileInput} type="file" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
                aria-label="Chọn tài liệu PDF hoặc ảnh" multiple disabled={working} hidden
                onChange={event => {chooseFiles(event.target.files, {replaceActive:pickerIntent.current === "replace"}); pickerIntent.current = "add"; event.target.value = "";}}/>
              <input ref={folderInput} type="file" webkitdirectory="" directory="" multiple hidden disabled={working}
                aria-label="Chọn thư mục tài liệu" onChange={event => {chooseFiles(event.target.files, {fromFolder:true}); event.target.value = "";}}/>

              {!documents.length ? <div className="drop-empty">
                <span className="drop-icon"><UploadCloud size={26} strokeWidth={1.6}/></span>
                <h3>Kéo thả tài liệu hoặc thư mục vào đây</h3>
                <p>PDF, PNG, JPG/JPEG · gồm cả thư mục con</p>
                <div className="drop-actions">
                  <Button size="sm" onClick={() => openFiles("add")}>Chọn tài liệu</Button>
                  <Button size="sm" variant="outline" onClick={() => folderInput.current?.click()}><FolderOpen size={15}/> Chọn thư mục</Button>
                </div>
                <p className="file-limits">Tối đa 15 MB/tệp · PDF: chỉ đọc trang 1 · Ảnh tối đa 12 MP</p>
              </div> : <>
                {notice && <Alert className="import-notice" role="status"><FolderOpen size={16}/><AlertTitle>Kết quả thêm tài liệu</AlertTitle>
                  <AlertDescription>{notice}<Button variant="ghost" size="sm" onClick={dismissNotice}>Đóng</Button></AlertDescription></Alert>}

                <DocumentQueue documents={documents} activeId={activeId} working={working} onSelect={selectDocument} onRemove={removeDocument}/>

                <div className={"preview-area" + (previewOpen ? "" : " collapsed")}>
                  {document && <div className="selected-file">
                    <FileIcon size={15}/>
                    <strong title={document.name}>{document.name}</strong>
                    <small>{(document.size / (1024 * 1024)).toFixed(2)} MB · {isPDF ? "PDF" : "Ảnh"}</small>
                    <Button variant="ghost" size="sm" disabled={working} onClick={() => openFiles("replace")}>Đổi tệp</Button>
                    <Button variant="ghost" size="icon" aria-expanded={previewOpen} aria-label={previewOpen ? "Ẩn xem trước" : "Hiện xem trước"} title={previewOpen ? "Ẩn xem trước để danh sách rộng hơn" : "Hiện xem trước"} onClick={() => setPreviewOpen(open => !open)}>
                      {previewOpen ? <ChevronDown size={15}/> : <ChevronUp size={15}/>}
                    </Button>
                  </div>}
                  {previewOpen && (preview ? <DocumentPreview url={preview} isPDF={isPDF} size={document?.size}/>
                    : <div className="preview-placeholder"><FileText size={28} strokeWidth={1.3}/><span>Chọn một tài liệu để xem trước</span></div>)}
                </div>
              </>}
            </div>

            <div className="pane-footer">
              <p className="mode-note" title={FAST_MODE_DESCRIPTION}>{FAST_MODE_DESCRIPTION}</p>
              {health === "not-ready" && <p className="model-alert" role="status"><AlertTriangle size={14}/> Thiếu model OCR: PDF có sẵn chữ vẫn bóc tách được; ảnh và bản scan cần model.</p>}

              <div className="input-actions">
                <div className={"run-buttons" + (documents.length > 1 ? " two" : "")}>
                  {/* With several documents the whole-list button is the main action; the selected one is secondary. */}
                  {done && documents.length < 2 ? <div className="run-done">
                    <span className="run-done-text" role="status"><CircleCheck size={16}/><span><strong>Đã bóc tách nhanh xong</strong> · {formatTime(result.elapsed_ms)}</span></span>
                    <Button className="run-button rerun-button" size="sm" variant="outline" onClick={() => runOcr()} disabled={!canRun}
                      title="Bóc tách lại văn bản này"><RotateCcw size={14}/>{RERUN_ONE_LABEL}</Button>
                  </div> : <Button className="run-button" size="lg" variant={documents.length > 1 ? "outline" : "default"} onClick={() => runOcr()} disabled={!document || working || !canRun}>
                    {working && batchProgress?.total === 1 ? <LoaderCircle className="spin" size={18}/> : done ? <RotateCcw size={16}/> : <ScanText size={18}/>}
                    {working && batchProgress?.total === 1 ? "Đang bóc tách…" : done ? RERUN_THIS_LABEL : RUN_ONE_FAST_LABEL}{!working && !done && <ArrowRight size={17}/>}
                  </Button>}
                  {documents.length > 1 && (working && batchProgress?.total > 1
                    ? <Button className="batch-pause-button" size="lg" variant="outline" onClick={pause} disabled={pausing}><Pause size={15}/>{pausing ? "Sẽ dừng sau tài liệu đang xử lý…" : "Tạm dừng hàng chờ"}</Button>
                    : resumeCount > 0
                      ? <Button className="batch-run-button batch-resume-button" size="lg" onClick={resume}><ListChecks size={18}/>{resumeLabel(resumeCount)}</Button>
                      : <Button className={"batch-run-button" + (allDone ? " rerun-all" : "")} size="lg" variant={allDone ? "outline" : "default"} onClick={runBatch} disabled={working || !canRunBatch}>
                        {allDone ? <RotateCcw size={16}/> : <ListChecks size={18}/>}{allDone ? rerunAllLabel(documents.length) : runAllLabel(documents.length)}</Button>)}
                </div>
                {batchProgress && documents.length > 1 && <div className="queue-progress" role="status">
                  {batchProgress.total > 1 && batchProgress.completed < batchProgress.total && <Progress value={100 * batchProgress.completed / batchProgress.total} aria-label="Tiến độ hàng chờ"/>}
                  <span>Đã xử lý {batchProgress.completed}/{batchProgress.total} tài liệu trong lượt này{working ? remainingText(batchProgress.remainingMs) : ""}
                    {batchProgress.paused && resumeCount ? ` · Đã tạm dừng, còn ${resumeCount} tài liệu: bấm “${RESUME_LABEL}” để chạy tiếp.` : ""}</span>
                </div>}
                {!working && failedCount > 0 && <Button className="batch-retry-button" variant="ghost" size="sm" onClick={runFailed} disabled={!canRunFailed}><RotateCcw size={14}/> Chạy lại {failedCount} tài liệu lỗi</Button>}
                {working && <div className="processing-status" role="status"><Progress value={null} className="processing-progress" aria-label="Đang xử lý, chưa có tiến độ phần trăm"/><span><Clock3 size={14}/> Đang xử lý trên máy · {elapsed.toFixed(0)} giây</span></div>}
                {error && <Alert variant="destructive" className="error-box"><AlertTriangle size={17}/><AlertTitle>Không thể hoàn tất thao tác</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>}
              </div>
            </div>
          </Card>

          <Card className="right-pane" aria-busy={working}>
            <div className="pane-header">
              <span className="pane-number">2</span>
              <div className="pane-title"><h2>Kết quả</h2><p>Metadata và nội dung header một phần</p></div>
              <Badge variant="outline" className={"document-state " + (result ? "complete" : "")} role="status">
                {result && <CircleCheck size={12}/>}{stateLabel}
              </Badge>
            </div>
            <Tabs className="result-tabs" value={activeView} onValueChange={value => {setActiveView(value); setCopied(false);}}>
              <div className="result-toolbar">
                <TabsList aria-label="Cách xem kết quả">
                  <TabsTrigger value="list">Danh sách văn bản</TabsTrigger>
                  <TabsTrigger value="metadata" disabled={!result}>Thông tin văn bản</TabsTrigger>
                  <TabsTrigger value="text">Header (một phần)</TabsTrigger>
                  <TabsTrigger value="page">Theo trang đã xét</TabsTrigger>
                </TabsList>
                <div className="toolbar-actions">
                  <ActionButton title="Sao chép header (một phần)" disabled={!result} onClick={copyText}>{copied ? <Check size={16}/> : <Copy size={16}/>}</ActionButton>
                  <ActionButton title="Tải TXT header (một phần)" disabled={!result} onClick={() => downloadText(shortName(document.name) + "_" + result.method + "_partial.txt", resultTextExport(result))}><Download size={16}/></ActionButton>
                  <ActionButton title="Tải JSON header (một phần)" disabled={!result} onClick={() => downloadText(shortName(document.name) + "_" + result.method + "_partial.json", JSON.stringify(result, null, 2), "application/json;charset=utf-8")}><FileJson size={16}/></ActionButton>
                </div>
              </div>
              {copied && <span className="copy-feedback" role="status"><Check size={14}/> Đã sao chép văn bản</span>}
              {activeView !== "list" && <DocumentNavigator documents={documents} activeId={activeId} onSelect={id => {
                // Stay on the same tab; a document without metadata falls back to its text.
                const target = documents.find(doc => doc.id === id);
                const view = activeView === "metadata" && !target?.metadataByMode[target.mode] ? "text" : activeView;
                selectDocument(id, view);
              }}/>}

              {result && activeView !== "list" && <div className="result-meta">
                <div className={"result-origin fast-origin " + (result.used_ocr ? "ocr-origin" : "native-origin")}>
                  <ShieldCheck size={14}/><span>Bóc tách nhanh · chỉ header trang 1</span>
                  <span className="partial-result-notice" role="status" title="Nội dung các trang chưa xét vẫn thuộc tài liệu nguồn.">{partialScope(result)}</span>
                </div>
                <div className="results-stats">
                  <span><b>{result.source_page_count}</b> trang nguồn</span><span><b>{result.line_count}</b> dòng header</span>
                  <span><Clock3 size={14}/><b>{formatTime(result.elapsed_ms)}</b></span>
                  {result.used_ocr && <span className={result.decoder_limit_hits > 0 ? "truncated-lines" : ""}><b>{result.decoder_limit_hits ?? "—"}</b> dòng bị cắt</span>}
                </div>
              </div>}

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
                  : result ? <pre>{shownText || "Không phát hiện được dòng văn bản. Hãy kiểm tra ảnh/PDF gốc."}</pre>
                  : <EmptyResult working={working} documentSelected={Boolean(document)}/>}
              </TabsContent>
            </Tabs>
          </Card>
        </section>
      </main>
      {pendingDiscard && <ConfirmDialog title={pendingDiscard.title || "Giữ hay thay thế chỉnh sửa?"} confirmLabel={pendingDiscard.confirmLabel || "Thay thế bản nháp"} onCancel={() => setPendingDiscard(null)}
        onConfirm={() => {const action = pendingDiscard.run; setPendingDiscard(null); action();}}><p>{pendingDiscard.message}</p></ConfirmDialog>}
    </div>
  </TooltipProvider>;
}

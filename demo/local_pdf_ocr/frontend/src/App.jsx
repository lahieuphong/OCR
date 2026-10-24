import React, {useEffect, useRef, useState} from "react";
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

const MAX_MB = 15;
const EXTENSIONS = /\.(pdf|png|jpe?g)$/i;
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
  const elapsedTimer = useRef(null);
  const [document, setDocument] = useState(null);
  const [preview, setPreview] = useState("");
  const [hoverUpload, setHoverUpload] = useState(false);
  const [selectedMode, setSelectedMode] = useState("vietocr_ocr");
  const [resultsByMode, setResultsByMode] = useState({});
  const [page, setPage] = useState(1);
  const [working, setWorking] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [health, setHealth] = useState("checking");
  const [activeView, setActiveView] = useState("text");
  const [healthAttempt, setHealthAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setHealth("checking");
    fetch("/api/health").then(async (response) => {
      if (!response.ok) throw Error("unhealthy");
      return response.json();
    }).then(data => {
      if (!cancelled) setHealth(data.state === "ready_to_initialize" ? "connected" : "not-ready");
    }).catch(() => { if (!cancelled) setHealth("disconnected"); });
    return () => { cancelled = true; };
  }, [healthAttempt]);

  useEffect(() => () => {
    if (elapsedTimer.current) window.clearInterval(elapsedTimer.current);
  }, []);
  useEffect(() => () => {if (preview) URL.revokeObjectURL(preview);}, [preview]);

  function chooseFile(file) {
    if (working || !file) return;
    setError("");
    if (!EXTENSIONS.test(file.name)) {
      setError("Vui lòng chọn tệp PDF, PNG hoặc JPG.");
      return;
    }
    if (file.size > MAX_MB * 1024 * 1024) {
      setError("Giới hạn kích thước tệp là 15 MB.");
      return;
    }
    if (file.size < 1) {
      setError("Tệp rỗng.");
      return;
    }
    setResultsByMode({});
    setActiveView("text");
    setPage(1);
    setCopied(false);
    setElapsed(0);
    setDocument(file);
    // Visible default only; users must explicitly run the selected mode.
    setSelectedMode(/\.pdf$/i.test(file.name) ? "native_text" : "vietocr_ocr");
    setPreview(URL.createObjectURL(file));
  }

  async function runOcr() {
    if (!document || working || !canRun) return;
    setWorking(true);
    setError("");
    if (activeView === "compare") setActiveView("text");
    setCopied(false);
    setResultsByMode(previous => ({...previous, [selectedMode]: undefined}));
    setElapsed(0);
    const start = performance.now();
    elapsedTimer.current = window.setInterval(
      () => setElapsed((performance.now() - start) / 1000), 350
    );
    try {
      const payload = new FormData();
      payload.append("file", document, document.name);
      payload.append("mode", selectedMode);
      const response = await fetch("/api/ocr", {method: "POST", body: payload});
      let data;
      try {
        data = await response.json();
      } catch {
        throw Error("Không đọc được phản hồi từ máy chủ xử lý. Vui lòng thử lại hoặc mở log trong cửa sổ trạng thái.");
      }
      if (!response.ok) throw Error(data.detail || "Không thể bóc tách văn bản. Vui lòng thử lại.");
      if (data.method !== selectedMode) {
        throw Error("Backend trả sai chế độ xử lý đã chọn; dừng để bảo vệ kết quả.");
      }
      if (!data.pages || !Array.isArray(data.pages)) {
        throw Error("Định dạng phản hồi từ backend không hợp lệ.");
      }
      setResultsByMode(previous => ({...previous, [selectedMode]: data}));
      setPage(1);
    } catch (exception) {
      setError(exception?.message || String(exception));
    } finally {
      window.clearInterval(elapsedTimer.current);
      setElapsed((performance.now() - start) / 1000);
      setWorking(false);
    }
  }

  const result = resultsByMode[selectedMode] || null;
  const currentPage = result?.pages.find(x => x.page === page);
  const shownText = activeView === "page" ? (currentPage?.text || "") : (result?.text || "");
  const isPDF = document && /\.pdf$/i.test(document.name);
  const FileIcon = isPDF ? FileText : FileImage;
  const bothReady = Boolean(isPDF && resultsByMode.native_text && resultsByMode.vietocr_ocr);
  const canRun = health === "connected" || (health === "not-ready" && selectedMode === "native_text");
  const stateLabel = working ? "Đang bóc tách" : error ? "Cần kiểm tra" : result ? "Hoàn tất" : document ? "Đã chọn tài liệu" : "Chưa chọn tài liệu";

  function changeMode(mode) {
    setSelectedMode(mode);
    setPage(1);
    setCopied(false);
    setError("");
    if (activeView === "compare") setActiveView("text");
  }

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
                onDrop={event => {event.preventDefault(); setHoverUpload(false); chooseFile(event.dataTransfer.files[0]);}}>
                <input ref={fileInput} type="file" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
                  aria-label="Chọn tài liệu PDF hoặc ảnh" disabled={working} hidden
                  onChange={event => {chooseFile(event.target.files?.[0]); event.target.value = "";}}/>
                {document ? <div className="selected-file">
                  <span className="selected-file-icon"><FileIcon size={23}/></span>
                  <div className="selected-file-info"><strong title={document.name}>{document.name}</strong>
                    <small>{(document.size / (1024 * 1024)).toFixed(2)} MB · {isPDF ? "Tài liệu PDF" : "Hình ảnh"}</small></div>
                  <Button variant="outline" size="sm" disabled={working} onClick={() => fileInput.current?.click()}>Đổi tệp</Button>
                </div> : <div className="drop-empty">
                  <UploadCloud size={25} strokeWidth={1.6}/>
                  <div><h3>Kéo thả tài liệu vào đây</h3><p>PDF, PNG, JPG/JPEG</p></div>
                  <Button size="sm" onClick={() => fileInput.current?.click()}>Chọn tài liệu</Button>
                </div>}
                <p className="file-limits">Tối đa 15 MB · PDF tối đa 6 trang · Ảnh tối đa 12 MP</p>
              </div>

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
              </fieldset>
              <p className="mode-note">{selectedMode === "native_text" ? "Đọc lớp chữ có sẵn trong PDF; không tự chuyển sang OCR." : "Nhận dạng trực tiếp từ hình ảnh; giữ nguyên kết quả nhận dạng."}</p>

              {health === "not-ready" && <Alert className="model-alert">
                <AlertTriangle size={16}/><AlertTitle>OCR chưa sẵn sàng</AlertTitle>
                <AlertDescription>Thiếu model hoặc model chưa hợp lệ. Bạn vẫn có thể trích xuất văn bản có sẵn trong PDF.</AlertDescription>
              </Alert>}

              <Button className="run-button" size="lg" onClick={runOcr} disabled={!document || working || !canRun}>
                {working ? <LoaderCircle className="spin" size={18}/> : <ScanText size={18}/>}
                {working ? "Đang bóc tách…" : "Bóc tách văn bản"}{!working && <ArrowRight size={17}/>}
              </Button>
              {working && <div className="processing-status" role="status"><Progress value={null} className="processing-progress" aria-label="Đang xử lý, chưa có tiến độ phần trăm"/><span><Clock3 size={14}/> Đang xử lý trên máy · {elapsed.toFixed(0)} giây</span></div>}
              {error && <Alert variant="destructive" className="error-box"><AlertTriangle size={17}/><AlertTitle>Không thể hoàn tất thao tác</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>}
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
                <ShieldCheck size={14}/><span>{result.used_ocr ? "Nhận dạng từ ảnh · PaddleOCR + VietOCR B1024" : "Trích xuất văn bản có sẵn trong PDF · Không chạy OCR"}</span>
              </div>
              <div className="results-stats">
                <span><b>{result.page_count}</b> trang</span><span><b>{result.line_count}</b> dòng</span>
                <span><Clock3 size={14}/><b>{formatTime(result.elapsed_ms)}</b></span>
                {result.used_ocr && <span className={result.decoder_limit_hits > 0 ? "truncated-lines" : ""}><b>{result.decoder_limit_hits ?? "—"}</b> dòng bị cắt</span>}
              </div>
            </>}

            {result && activeView === "page" && <nav className="page-tabs" aria-label="Chọn trang kết quả">
              <Button variant="outline" size="icon" aria-label="Trang trước" disabled={page === result.pages[0]?.page} onClick={() => setPage(result.pages[result.pages.findIndex(item => item.page === page) - 1]?.page ?? page)}><ChevronLeft size={16}/></Button>
              {result.pages.map(item => <Button key={item.page} variant={page === item.page ? "default" : "ghost"} size="sm" aria-current={page === item.page ? "page" : undefined} onClick={() => {setPage(item.page); setCopied(false);}}>Trang {item.page}</Button>)}
              <Button variant="outline" size="icon" aria-label="Trang sau" disabled={page === result.pages.at(-1)?.page} onClick={() => setPage(result.pages[result.pages.findIndex(item => item.page === page) + 1]?.page ?? page)}><ChevronRight size={16}/></Button>
            </nav>}

            <TabsContent value={activeView} className={"text-output " + (!result ? "empty-result" : "")} aria-label="Nội dung văn bản">
              {result && activeView === "compare" && bothReady ? <div className="comparison-columns">
                <section><h3>Văn bản có sẵn trong PDF</h3><pre>{resultsByMode.native_text.text}</pre></section>
                <section><h3>Nhận dạng từ ảnh/PDF</h3><pre>{resultsByMode.vietocr_ocr.text}</pre></section>
              </div> : result ? <pre>{shownText || "Không phát hiện được dòng văn bản. Hãy kiểm tra ảnh/PDF gốc."}</pre>
                : <EmptyResult working={working} documentSelected={Boolean(document)} nativeText={selectedMode === "native_text"}/>}
            </TabsContent>
            </Tabs>
            <div className="output-bottom"><ShieldCheck size={14}/><span>Giữ nguyên nội dung và dấu tiếng Việt</span><span className="output-format">TXT / JSON</span></div>
          </Card>
        </section>
        <footer className="footer"><span><LockKeyhole size={13}/> Tài liệu được xử lý trên máy tính của bạn</span><span>Bản thử nghiệm nội bộ</span></footer>
      </main>
    </div>
  </TooltipProvider>;
}

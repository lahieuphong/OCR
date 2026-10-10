import React, {useEffect, useRef, useState} from "react";
import {
  ScanText, FileText, FileImage, UploadCloud, ShieldCheck, Cpu,
  Sparkles, ChevronRight, Download, Copy, Check, AlertTriangle,
  LoaderCircle, Clock3, Layers3, RotateCcw, FileCode2, Info, ScanLine,
} from "lucide-react";

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

export default function App() {
  const fileInput = useRef(null);
  const elapsedTimer = useRef(null);
  const [document, setDocument] = useState(null);
  const [preview, setPreview] = useState("");
  const [hoverUpload, setHoverUpload] = useState(false);
  const [selectedMode, setSelectedMode] = useState("vietocr_ocr");
  const [resultsByMode, setResultsByMode] = useState({});
  const [compare, setCompare] = useState(false);
  const [page, setPage] = useState(1);
  const [working, setWorking] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [health, setHealth] = useState("checking");
  const [activeView, setActiveView] = useState("text");

  useEffect(() => {
    let cancelled = false;
    fetch("/api/health").then(async (response) => {
      if (!response.ok) throw Error("unhealthy");
      return response.json();
    }).then(data => {
      if (!cancelled) setHealth(data.state === "ready_to_initialize" ? "connected" : "not-ready");
    }).catch(() => { if (!cancelled) setHealth("disconnected"); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => () => {
    if (elapsedTimer.current) window.clearInterval(elapsedTimer.current);
  }, []);
  useEffect(() => () => {if (preview) URL.revokeObjectURL(preview);}, [preview]);

  function chooseFile(file) {
    if (working || !file) return;
    setError("");
    setResultsByMode({});
    setCompare(false);
    setPage(1);
    setCopied(false);
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
    setDocument(file);
    // Visible default only; users must explicitly run the selected mode.
    setSelectedMode(/\.pdf$/i.test(file.name) ? "native_text" : "vietocr_ocr");
    setPreview(URL.createObjectURL(file));
  }

  async function runOcr() {
    if (!document || working) return;
    setWorking(true);
    setError("");
    setCompare(false);
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
        throw Error("Backend không trả về JSON. Kiểm tra cửa sổ CMD của FastAPI.");
      }
      if (!response.ok) throw Error(data.detail || "OCR thất bại.");
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
  const icon = isPDF ? FileText : FileImage;
  const bothReady = Boolean(isPDF && resultsByMode.native_text && resultsByMode.vietocr_ocr);
  const canRun = health === "connected" || (health === "not-ready" && selectedMode === "native_text");

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

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="VietDoc OCR">
          <span className="brand-mark"><ScanText size={22}/></span>
          <span>VietDoc<span className="brand-accent">OCR</span></span>
        </a>
        <div className="topbar-center"><span className="topbar-line"/> Document intelligence <span className="topbar-line"/></div>
        <div className="topbar-right">
          <span className="environment-label">LOCAL EXPERIMENT</span>
          <span className={"server-pill " + health}>
            <span className="server-dot"/>
            {health === "connected" ? "Backend kết nối" : health === "checking" ? "Đang kiểm tra" : health === "not-ready" ? "Thiếu model" : "Backend chưa bật"}
          </span>
        </div>
      </header>

      <main className="main-container">
        <section className="hero">
          <div className="eyebrow"><Sparkles size={15}/> VIETNAMESE DOCUMENT RECOGNITION <span className="eyebrow-divider"/> V1 EXPERIMENTAL</div>
          <h1>Chuyển tài liệu thành <em>văn bản.</em></h1>
          <p>Trích xuất văn bản từ PDF có sẵn text hoặc nhận dạng PDF scan và ảnh bằng PaddleOCR Detection + VietOCR B. Hai phương pháp độc lập, không tự động thay thế lẫn nhau.</p>
          <div className="hero-meta">
            <span><ShieldCheck size={15}/> Xử lý trên máy của bạn</span>
            <span><Cpu size={15}/> ONNX Runtime CPU</span>
            <span><Layers3 size={15}/> Giữ nguyên dấu tiếng Việt</span>
          </div>
        </section>

        <section className="workspace">
          <div className="left-pane">
            <div className="pane-header">
              <span className="pane-icon"><UploadCloud size={19}/></span>
              <div><h2>Tài liệu đầu vào</h2><p>PDF · PNG · JPG</p></div>
              <span className="pane-step">01 / INPUT</span>
            </div>

            <div
              className={"dropzone " + (hoverUpload ? "drag-over " : "") + (document ? "has-file" : "")}
              role="button"
              tabIndex={0}
              onKeyDown={event => {if(event.key === "Enter" || event.key === " ") {event.preventDefault(); fileInput.current?.click();}}}
              onClick={() => {if (!working) fileInput.current?.click();}}
              onDragOver={event => {event.preventDefault(); setHoverUpload(true);}}
              onDragLeave={() => setHoverUpload(false)}
              onDrop={event => {
                event.preventDefault(); setHoverUpload(false);
                chooseFile(event.dataTransfer.files[0]);
              }}
            >
              <input ref={fileInput} type="file" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
                hidden onChange={event => {chooseFile(event.target.files?.[0]); event.target.value = "";}}/>
              {document ? (
                <div className="selected-file">
                  <div className="selected-file-icon">{React.createElement(icon, {size:27})}</div>
                  <div className="selected-file-info">
                    <strong title={document.name}>{document.name}</strong>
                    <small>{(document.size / (1024*1024)).toFixed(2)} MB · Nhấn để chọn file khác</small>
                  </div>
                  <RotateCcw size={17} className="replace-icon"/>
                </div>
              ) : (
                <div className="drop-empty">
                  <span className="drop-icon"><UploadCloud size={29}/></span>
                  <h3>Kéo & thả tài liệu vào đây</h3>
                  <p>Hoặc nhấn để chọn tệp từ máy tính</p>
                  <span className="pick-file">Chọn tài liệu <ChevronRight size={15}/></span>
                  <small>Giới hạn 15 MB · PDF tối đa 6 trang</small>
                </div>
              )}
            </div>


            <fieldset className="ocr-mode-selector" disabled={!document || working}>
              <legend>02 · CHỌN PHƯƠNG PHÁP</legend>
              <label className={"mode-option " + (selectedMode === "native_text" ? "selected" : "") + (!isPDF ? " unavailable" : "")}>
                <input type="radio" name="mode" value="native_text"
                  checked={selectedMode === "native_text"}
                  onChange={() => {setSelectedMode("native_text"); setPage(1); setError(""); setCompare(false);}}
                  disabled={!isPDF || working}/>
                <span className="mode-name"><FileText size={16}/> Text có sẵn trong PDF</span>
                <small>PyMuPDF · nhanh · không chạy OCR</small>
                {resultsByMode.native_text && <span className="mode-done"><Check size={12}/> Đã chạy</span>}
              </label>
              <label className={"mode-option " + (selectedMode === "vietocr_ocr" ? "selected" : "")}>
                <input type="radio" name="mode" value="vietocr_ocr"
                  checked={selectedMode === "vietocr_ocr"}
                  onChange={() => {setSelectedMode("vietocr_ocr"); setPage(1); setError(""); setCompare(false);}}
                  disabled={working}/>
                <span className="mode-name"><ScanLine size={16}/> OCR bằng VietOCR B</span>
                <small>PaddleOCR Detection · ONNX CPU · PDF/ảnh</small>
                {resultsByMode.vietocr_ocr && <span className="mode-done"><Check size={12}/> Đã chạy</span>}
              </label>
              <p className="mode-note">
                {selectedMode === "native_text"
                  ? "Chỉ đọc lớp chữ nhúng trong PDF. PDF scan không có text sẽ báo lỗi, không tự chuyển sang OCR."
                  : "Luôn render trang và chạy nhận dạng thực sự, kể cả PDF đã có text. Kết quả không bị chỉnh sửa dấu."}
              </p>
            </fieldset>

            <div className="preview-area">
              <div className="section-label"><span>01</span> XEM TRƯỚC <span className="subtle-line"/></div>
              {preview ? (
                isPDF ? <iframe className="pdf-view" src={preview+"#toolbar=0"} title="Bản xem trước PDF"/> :
                  <div className="image-view"><img src={preview} alt="Bản xem trước tài liệu"/></div>
              ) : (
                <div className="preview-placeholder">
                  <FileText size={42} strokeWidth={1.2}/>
                  <strong>Tài liệu sẽ hiển thị ở đây</strong>
                  <span>Chọn một file để bắt đầu xem trước</span>
                </div>
              )}
            </div>

            <button className="run-button" type="button" onClick={runOcr}
              disabled={!document || working || !canRun}>
              {working ? <><LoaderCircle className="spin" size={19}/> Đang xử lý...</> :
                <><ScanLine size={19}/>{selectedMode === "native_text" ? "Trích xuất text PDF" : "Chạy PaddleOCR + VietOCR"} <ChevronRight size={19}/></>}
            </button>
            {working && <div className="processing-status"><Clock3 size={14}/> Đang xử lý tại máy · {elapsed.toFixed(0)} giây. Vui lòng đợi và giữ trang mở.</div>}
            {error && <div className="error-box" role="alert"><AlertTriangle size={18}/><span>{error}</span></div>}
          </div>

          <div className="right-pane">
            <div className="pane-header">
              <span className="pane-icon recognition"><FileCode2 size={19}/></span>
              <div><h2>Kết quả tài liệu</h2><p>{selectedMode === "native_text" ? "Từ text layer PDF · không OCR" : "Từ nhận dạng hình ảnh · VietOCR B"}</p></div>
              <span className="pane-step">02 / OUTPUT</span>
            </div>

            <div className="result-toolbar">
              <div className="view-toggle">
                <button className={activeView === "text" ? "active" : ""} onClick={() => setActiveView("text")}>Toàn văn</button>
                <button className={activeView === "page" ? "active" : ""} onClick={() => setActiveView("page")}>Theo trang</button>
                {bothReady && <button className={compare ? "active" : ""} onClick={() => setCompare(!compare)}>So sánh</button>}
              </div>
              <div className="toolbar-actions">
                <button title="Sao chép văn bản" disabled={!result} onClick={copyText}>{copied ? <Check size={17}/> : <Copy size={17}/>}</button>
                <button title="Tải TXT" disabled={!result} onClick={() => downloadText(shortName(document.name) + "_" + result.method + ".txt", result.text)}><Download size={17}/></button>
                <button title="Tải báo cáo JSON" disabled={!result} onClick={() => downloadText(shortName(document.name) + "_" + result.method + ".json", JSON.stringify(result, null, 2), "application/json;charset=utf-8")}><FileCode2 size={17}/></button>
              </div>
            </div>

            {result && <div className={"result-origin " + (result.used_ocr ? "ocr-origin" : "native-origin")}>
              <ShieldCheck size={15}/>
              <span>{result.used_ocr
                ? "NGUỒN: PaddleOCR Detection + VietOCR B / ONNX CPU"
                : "NGUỒN: Văn bản nhúng PDF / PyMuPDF — KHÔNG chạy OCR"}</span>
            </div>}
            {result && !result.used_ocr && result.native_text_complete === false &&
              <div className="review-warning" role="status"><AlertTriangle size={17}/>
                <span>PDF này chứa ảnh scan hoặc trang thiếu text layer. Chế độ 1 chỉ trích xuất được phần chữ nhúng (có thể chỉ là thông tin ký số). Cần chạy chế độ OCR để lấy nội dung các trang {result.pages_requiring_ocr?.join(", ")}.</span>
              </div>}
            {result && result.used_ocr && result.pages?.some(p => p.detection_review?.review_required || p.reading_order?.review_source_line_indices?.length > 0) &&
              <div className="review-warning" role="status"><AlertTriangle size={17}/>
                <span>Có vùng OCR cần rà soát (header gộp, dòng gần dấu, hoặc mảnh chữ nằm giữa hai cột). Kết quả vẫn giữ nguyên từng ký tự nhận dạng; xem detection_review và reading_order trong JSON.</span>
              </div>}
            {result && <div className="results-stats">
              <div><b>{result.page_count}</b><small>trang</small></div>
              <div><b>{result.line_count}</b><small>dòng nhận dạng</small></div>
              <div><b>{formatTime(result.elapsed_ms)}</b><small>thời gian xử lý</small></div>
              <div><b>{result.decoder_limit_hits ?? "—"}</b><small>{result.used_ocr ? "dòng bị cắt" : "không dùng decoder"}</small></div>
            </div>}

            {result && activeView === "page" && <div className="page-tabs">
              {result.pages.map(item => <button key={item.page} className={page === item.page ? "active" : ""} onClick={() => setPage(item.page)}>Trang {item.page}</button>)}
            </div>}

            <div className={"text-output " + (!result ? "empty-result" : "")}>
              {result && compare && bothReady ? (
                <div className="comparison-columns">
                  <section><strong>PDF text layer · PyMuPDF</strong>
                    <pre>{resultsByMode.native_text.text}</pre></section>
                  <section><strong>OCR thực · VietOCR B</strong>
                    <pre>{resultsByMode.vietocr_ocr.text}</pre></section>
                </div>
              ) : result ? (
                <pre>{shownText || "Không phát hiện được dòng văn bản. Hãy kiểm tra ảnh/PDF gốc."}</pre>
              ) : working ? (
                <div className="result-placeholder">
                  <span className="result-icon active-icon"><LoaderCircle className="spin" size={34}/></span>
                  <h3>Đang phân tích tài liệu...</h3>
                  <p>{selectedMode === "native_text"
                    ? "Đang đọc lớp văn bản nhúng trong PDF, không chạy OCR."
                    : "Phát hiện dòng chữ, chuẩn hóa crop và giải mã VietOCR B."}</p>
                </div>
              ) : (
                <div className="result-placeholder">
                  <span className="result-icon"><ScanText size={36}/></span>
                  <h3>Sẵn sàng bóc tách</h3>
                  <p>Kết quả OCR sẽ xuất hiện tại đây ngay sau khi xử lý.</p>
                  <div className="result-placeholder-hint"><Sparkles size={15}/> Chọn một phương pháp ở cột trái rồi chạy</div>
                </div>
              )}
            </div>

            <div className="output-bottom">
              <div className="model-inline"><span className="model-dot"/><span>{result?.used_ocr || selectedMode === "vietocr_ocr" ? "VIETOCR B / WIDTH 1024" : "PDF TEXT LAYER / PYMUPDF"}</span><span className="model-divider">/</span><span>{selectedMode === "vietocr_ocr" ? "ONNX CPU" : "NO OCR"}</span></div>
              {result ? <span className="model-note">Experimental · cần kiểm thử PDF end-to-end</span> :
                <span className="model-note">Hai chế độ độc lập · Không dùng text nhúng để che lỗi OCR</span>}
            </div>
          </div>
        </section>

        <footer className="footer">
          <div><ShieldCheck size={16}/> Local-only · Không tự tải tài liệu lên Internet</div>
          <div><Info size={16}/> Prototype phục vụ demo · Chưa được phê duyệt production</div>
        </footer>
      </main>
    </div>
  );
}

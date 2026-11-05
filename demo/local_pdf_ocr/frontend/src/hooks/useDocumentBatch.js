import {useEffect, useReducer, useRef, useState} from "react";
import {batchReducer, createBatchDocument, estimateRemainingMs, modeAllowed, runDocumentQueue} from "@/lib/documentBatch.js";
import {createDocumentDraft, validateDocumentDraft} from "@/lib/documentFields.js";
import {describeImport, documentPath, planImport} from "@/lib/folderImport.js";


// The 22 fields are the main purpose: every document added in the app starts with the fast header mode
// (first page only, about 7-15 s per PDF). Full text (native/OCR/H1) stays one click away.
export const NEW_DOCUMENT_MODE = "metadata_fast";

export default function useDocumentBatch(health) {
  const [documents, dispatch] = useReducer(batchReducer, []);
  const [activeId, setActiveId] = useState(null);
  const [preview, setPreview] = useState("");
  const [working, setWorking] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [uiError, setError] = useState("");
  const [activeView, setActiveView] = useState("text");
  const [pendingDiscard, setPendingDiscard] = useState(null);
  const [batchProgress, setBatchProgress] = useState(null);
  const [pausing, setPausing] = useState(false);
  const [notice, setNotice] = useState("");
  const running = useRef(false), timer = useRef(null), mounted = useRef(true), pauseRequested = useRef(false);
  const active = documents.find(doc => doc.id === activeId) || null;
  const document = active?.file || null;
  const selectedMode = active?.mode || "vietocr_ocr";
  const resultsByMode = active?.resultsByMode || {};
  const metadataByMode = active?.metadataByMode || {};
  // Fast PDF headers with a genuine text layer can work without models. If OCR
  // is needed the backend refuses that request; never fall back to e-sign text.
  // Without models only a PDF's own text works: the text layer, or a fast header from it. An image always needs OCR.
  const canRunMode = (mode, name = active?.name || "") => health === "connected"
    || (health === "not-ready" && (mode === "native_text" || (mode === "metadata_fast" && /\.pdf$/iu.test(name))));
  const canRun = canRunMode(selectedMode);
  const pending = documents.filter(doc => !doc.resultsByMode[doc.mode]);
  const canRunBatch = pending.length > 0 && pending.every(doc => canRunMode(doc.mode, doc.name));
  const failed = documents.filter(doc => doc.errorsByMode[doc.mode]);
  const canRunFailed = failed.length > 0 && failed.every(doc => canRunMode(doc.mode, doc.name));

  useEffect(() => {
    mounted.current = true;
    return () => {mounted.current = false; window.clearInterval(timer.current);};
  }, []);
  useEffect(() => {
    if (!document) {setPreview(""); return;}
    const url = URL.createObjectURL(document); setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [document]);
  function update(id, transform) {dispatch({type:"update",id,update:transform});}
  function setMetadataByMode(transform) {
    update(activeId, doc => ({...doc,metadataByMode:typeof transform === "function" ? transform(doc.metadataByMode) : transform,
      confirmedByMode:{...doc.confirmedByMode,[doc.mode]:false}}));
  }
  function selectDocument(id, view) {
    const doc = documents.find(item => item.id === id);
    if (!doc) return;
    setActiveId(id); setError("");
    setActiveView(view || (doc.metadataByMode[doc.mode] ? "metadata" : "text"));
  }
  // files: a FileList/array from the file picker, the folder picker (webkitRelativePath) or a drop.
  function chooseFiles(files, {replaceActive = false, fromFolder = false} = {}) {
    if (running.current) return;
    const list = Array.from(files || []);
    fromFolder ||= list.some(file => file.webkitRelativePath || file.vietdocPath);
    const kept = replaceActive && active ? documents.filter(doc => doc.id !== active.id) : documents;
    const plan = planImport(list, {existing: kept.map(doc => doc.file), fromFolder});
    const valid = plan.accepted.map(file => createBatchDocument(file, undefined, {path: documentPath(file), mode: NEW_DOCUMENT_MODE}));
    // Skipped files next to added ones are information, not a failed action; nothing added is an error.
    const summary = fromFolder && !list.length ? "Thư mục không có tệp nào." : describeImport(plan, {fromFolder});
    setError(valid.length ? "" : summary); setNotice(valid.length ? summary : "");
    if (!valid.length) return;
    if (fromFolder) replaceActive = false;  // a folder always adds to the list
    const apply = () => {
      if (replaceActive && active) {
        dispatch({type:"replace",id:active.id,document:valid[0]});
        if (valid.length > 1) dispatch({type:"add",documents:valid.slice(1)});
      } else dispatch({type:"add",documents:valid});
      setActiveId(valid[0].id); setActiveView("text"); setBatchProgress(null); setElapsed(0);
    };
    if (replaceActive && active && Object.values(active.metadataByMode).some(draft => draft.dirty)) {
      setPendingDiscard({run:apply,message:"Đổi tệp sẽ thay thế các bản nháp metadata đã chỉnh sửa của tài liệu đang chọn. Các tài liệu khác được giữ nguyên."});
    } else apply();
  }
  function removeDocument(id) {
    if (running.current) return;
    const doc = documents.find(item => item.id === id);
    const apply = () => {
      dispatch({type:"remove",id});
      if (activeId === id) {
        const next = documents.find(item => item.id !== id);
        setActiveId(next?.id || null); setActiveView(next?.metadataByMode[next.mode] ? "metadata" : "text");
      }
      setError("");
    };
    if (doc && Object.values(doc.metadataByMode).some(draft => draft.dirty)) setPendingDiscard({run:apply,message:"Xóa tài liệu sẽ mất các chỉnh sửa metadata của tài liệu này."});
    else apply();
  }
  function changeMode(mode, id = activeId) {
    const target = documents.find(doc => doc.id === id);
    if (!target || running.current || !modeAllowed(target.name, mode)) return;
    update(target.id, doc => ({...doc,mode})); setError("");
    if (id === activeId) setActiveView(target.metadataByMode[mode] ? "metadata" : "text");
  }
  // One method for every document still without a result; finished results and edits are untouched.
  // Images keep their own method when the chosen one needs a PDF text layer.
  function changeModeForPending(mode) {
    if (running.current) return 0;
    const targets = documents.filter(doc => !doc.resultsByMode[doc.mode] && modeAllowed(doc.name, mode) && doc.mode !== mode);
    for (const doc of targets) update(doc.id, current => ({...current,mode}));
    setError("");
    return targets.length;
  }
  // Pause = stop after the document being processed (a request is never cut off); "continue" runs what is left.
  function pause() {
    if (!running.current) return;
    pauseRequested.current = true; setPausing(true);
  }
  async function process(entries, batch = false) {
    if (running.current || !entries.length || entries.some(doc => !canRunMode(doc.mode, doc.name))) return;
    running.current = true; pauseRequested.current = false; setPausing(false);
    setWorking(true); setError(""); setNotice("");
    const startedAt = Date.now();
    setBatchProgress({completed:0,total:entries.length,remainingMs:null,paused:false});
    if (batch) setActiveView("list");
    let completedCount = 0;
    try {
      await runDocumentQueue(entries, {
        shouldContinue:() => mounted.current && !pauseRequested.current,
        onStart:doc => {
          setActiveId(doc.id); if (!batch) setActiveView("text"); setElapsed(0);
          const start = performance.now(); window.clearInterval(timer.current);
          timer.current = window.setInterval(() => setElapsed((performance.now() - start) / 1000),350);
          update(doc.id, current => ({...current,resultsByMode:{...current.resultsByMode,[doc.mode]:undefined},
            errorsByMode:{...current.errorsByMode,[doc.mode]:""},statesByMode:{...current.statesByMode,[doc.mode]:"processing"}}));
        },
        onSuccess:(doc, {raw,draft}) => {
          update(doc.id, current => {
            const baseline = doc.mode === "hybrid_h1" && raw.ocr_result?.method === "vietocr_ocr"
              && !current.resultsByMode.vietocr_ocr ? raw.ocr_result : null;
            return {...current,resultsByMode:{...current.resultsByMode,...(baseline ? {vietocr_ocr:baseline} : {}),[doc.mode]:raw},
              metadataByMode:{...current.metadataByMode,...(baseline ? {vietocr_ocr:createDocumentDraft(baseline,{sourceKind:"pdf"})} : {}),[doc.mode]:draft},
              errorsByMode:{...current.errorsByMode,...(baseline ? {vietocr_ocr:""} : {}),[doc.mode]:""},
              statesByMode:{...current.statesByMode,...(baseline ? {vietocr_ocr:"success"} : {}),[doc.mode]:"success"},
              confirmedByMode:{...current.confirmedByMode,...(baseline ? {vietocr_ocr:false} : {}),[doc.mode]:false}};
          });
          if (!batch) setActiveView("metadata");
        },
        onError:(doc,error) => {
          update(doc.id, current => ({...current,resultsByMode:{...current.resultsByMode,[doc.mode]:doc.resultsByMode[doc.mode]},
            errorsByMode:{...current.errorsByMode,[doc.mode]:error},statesByMode:{...current.statesByMode,[doc.mode]:"error"}}));
          if (!batch && doc.resultsByMode[doc.mode]) setActiveView("metadata");
        },
        onProgress:(completed,total) => {
          window.clearInterval(timer.current); completedCount = completed;
          setBatchProgress({completed,total,remainingMs:estimateRemainingMs(startedAt,completed,total),paused:false});
        },
      });
      if (batch && mounted.current) setActiveView("list");
    } finally {
      window.clearInterval(timer.current); running.current = false;
      const paused = pauseRequested.current && completedCount < entries.length; pauseRequested.current = false;
      if (mounted.current) {
        setWorking(false); setPausing(false);
        if (paused) setBatchProgress(progress => ({...progress,remainingMs:null,paused:true}));
      }
    }
  }
  function runOcr(id = activeId) {
    const doc = documents.find(item => item.id === id);
    if (!doc || !canRunMode(doc.mode, doc.name)) return;
    if (doc.metadataByMode[doc.mode]?.dirty) setPendingDiscard({run:() => process([doc]),message:"Chạy lại sẽ thay thế bản nháp metadata đã chỉnh sửa của phương pháp đang chọn nếu xử lý thành công."});
    else process([doc]);
  }
  function restoreMetadata() {
    const restore = () => setMetadataByMode(previous => ({...previous,[selectedMode]:createDocumentDraft(resultsByMode[selectedMode],{sourceKind:/\.pdf$/iu.test(document.name) ? "pdf" : "image"})}));
    if (metadataByMode[selectedMode]?.dirty) setPendingDiscard({run:restore,message:"Khôi phục sẽ xóa các giá trị metadata bạn đã chỉnh sửa hoặc xác nhận. Văn bản OCR gốc được giữ nguyên."});
    else restore();
  }
  function confirmDocument(id) {
    const doc = documents.find(item => item.id === id), draft = doc?.metadataByMode[doc.mode];
    if (!draft || Object.keys(validateDocumentDraft(draft).errors).length) {setError("Cần sửa metadata không hợp lệ trước khi xác nhận tài liệu."); return;}
    setPendingDiscard({title:"Xác nhận đã kiểm tra tài liệu",confirmLabel:"Đã kiểm tra",message:"Xác nhận bạn đã đối chiếu tài liệu này. Các trường chưa xác định vẫn giữ rỗng; cảnh báo chế độ sử dụng chưa phân loại vẫn áp dụng khi xuất.",
      run:() => update(id, current => ({...current,confirmedByMode:{...current.confirmedByMode,[doc.mode]:true}}))});
  }
  return {documents,activeId,active,document,preview,selectedMode,resultsByMode,metadataByMode,setMetadataByMode,
    pendingDiscard,setPendingDiscard,working,elapsed,error:uiError || active?.errorsByMode[selectedMode] || "",setError,
    activeView,setActiveView,canRun,canRunBatch,batchProgress,chooseFiles,selectDocument,removeDocument,changeMode,restoreMetadata,
    runOcr,runBatch:() => process(pending,true),confirmDocument,
    pendingCount:pending.length,failedCount:failed.length,canRunFailed,runFailed:() => process(failed,true),
    changeModeForPending,pause,pausing,notice,dismissNotice:() => setNotice(""),
    setIncluded:(id,checked) => update(id, doc => ({...doc,includeInExport:checked}))};
}

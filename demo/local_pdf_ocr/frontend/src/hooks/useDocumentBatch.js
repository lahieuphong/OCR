import {useEffect, useReducer, useRef, useState} from "react";
import {batchReducer, createBatchDocument, runDocumentQueue} from "@/lib/documentBatch.js";
import {createDocumentDraft, validateDocumentDraft} from "@/lib/documentFields.js";

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
  const running = useRef(false), timer = useRef(null), mounted = useRef(true);
  const active = documents.find(doc => doc.id === activeId) || null;
  const document = active?.file || null;
  const selectedMode = active?.mode || "vietocr_ocr";
  const resultsByMode = active?.resultsByMode || {};
  const metadataByMode = active?.metadataByMode || {};
  const canRunMode = mode => health === "connected" || (health === "not-ready" && mode === "native_text");
  const canRun = canRunMode(selectedMode);
  const pending = documents.filter(doc => !doc.resultsByMode[doc.mode]);
  const canRunBatch = pending.length > 0 && pending.every(doc => canRunMode(doc.mode));

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
  function chooseFiles(files, {replaceActive = false} = {}) {
    if (running.current) return;
    const issues = [], valid = [];
    for (const file of Array.from(files || [])) {
      if (!/\.(pdf|png|jpe?g)$/iu.test(file.name)) issues.push(`${file.name}: Vui lòng chọn tệp PDF, PNG hoặc JPG.`);
      else if (file.size > 15 * 1024 * 1024) issues.push(`${file.name}: Giới hạn kích thước tệp là 15 MB.`);
      else if (file.size < 1) issues.push(`${file.name}: Tệp rỗng.`);
      else valid.push(createBatchDocument(file));
    }
    setError(issues.join("\n"));
    if (!valid.length) return;
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
    if (!target || running.current || (!/\.pdf$/iu.test(target.name) && mode !== "vietocr_ocr")) return;
    update(target.id, doc => ({...doc,mode})); setError("");
    if (id === activeId) setActiveView(target.metadataByMode[mode] ? "metadata" : "text");
  }
  async function process(entries, batch = false) {
    if (running.current || !entries.length || entries.some(doc => !canRunMode(doc.mode))) return;
    running.current = true; setWorking(true); setError(""); setBatchProgress({completed:0,total:entries.length});
    try {
      await runDocumentQueue(entries, {
        shouldContinue:() => mounted.current,
        onStart:doc => {
          setActiveId(doc.id); setActiveView("text"); setElapsed(0);
          const start = performance.now(); window.clearInterval(timer.current);
          timer.current = window.setInterval(() => setElapsed((performance.now() - start) / 1000),350);
          update(doc.id, current => ({...current,resultsByMode:{...current.resultsByMode,[doc.mode]:undefined},
            errorsByMode:{...current.errorsByMode,[doc.mode]:""},statesByMode:{...current.statesByMode,[doc.mode]:"processing"}}));
        },
        onSuccess:(doc, {raw,draft}) => {
          update(doc.id, current => ({...current,resultsByMode:{...current.resultsByMode,[doc.mode]:raw},
            metadataByMode:{...current.metadataByMode,[doc.mode]:draft},errorsByMode:{...current.errorsByMode,[doc.mode]:""},
            statesByMode:{...current.statesByMode,[doc.mode]:"success"},confirmedByMode:{...current.confirmedByMode,[doc.mode]:false}}));
          if (!batch) setActiveView("metadata");
        },
        onError:(doc,error) => {
          update(doc.id, current => ({...current,resultsByMode:{...current.resultsByMode,[doc.mode]:doc.resultsByMode[doc.mode]},
            errorsByMode:{...current.errorsByMode,[doc.mode]:error},statesByMode:{...current.statesByMode,[doc.mode]:"error"}}));
          if (!batch && doc.resultsByMode[doc.mode]) setActiveView("metadata");
        },
        onProgress:(completed,total) => {window.clearInterval(timer.current); setBatchProgress({completed,total});},
      });
      if (batch && mounted.current) setActiveView("list");
    } finally {window.clearInterval(timer.current); running.current = false; if (mounted.current) setWorking(false);}
  }
  function runOcr(id = activeId) {
    const doc = documents.find(item => item.id === id);
    if (!doc || !canRunMode(doc.mode)) return;
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
    setIncluded:(id,checked) => update(id, doc => ({...doc,includeInExport:checked}))};
}

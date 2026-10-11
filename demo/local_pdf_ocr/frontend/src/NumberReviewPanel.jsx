import React, {useEffect, useMemo, useState} from "react";
import {AlertTriangle, CheckCircle2, Download, Eye, FileSearch} from "lucide-react";
import {findNumberReviewCandidates, REASONS} from "./numberReview.js";

function downloadAudit(filename, object) {
  const url=URL.createObjectURL(new Blob([JSON.stringify(object,null,2)],{type:"application/json;charset=utf-8"}));
  const a=window.document.createElement("a");
  a.href=url;a.download=filename;window.document.body.append(a);a.click();a.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}

/** A separate, opt-in review lane. Never calls setResult or edits result.text. */
export default function NumberReviewPanel({sourceFile, result}) {
  const candidates=useMemo(()=>findNumberReviewCandidates(result),[result]);
  const [chosen,setChosen]=useState(0);
  const [notes,setNotes]=useState({});
  const [draft,setDraft]=useState("");
  const [crop,setCrop]=useState("");
  const [loading,setLoading]=useState(false);
  const [cropError,setCropError]=useState("");
  const [feedback,setFeedback]=useState("");
  const selected=candidates[chosen]||null;

  useEffect(()=>{setChosen(0);setNotes({});setFeedback("");},[result,sourceFile]);
  useEffect(()=>{
    if(selected)setDraft(notes[selected.review_key]?.reviewed_text??selected.text);
    else setDraft("");
  },[selected?.review_key,notes]);
  useEffect(()=>{
    let live=true;const controller=new AbortController();let objectURL="";
    setCrop("");setCropError("");setLoading(Boolean(selected?.polygon));
    if(!selected?.polygon||!sourceFile){setLoading(false);return ()=>{controller.abort();};}
    async function render(){
      const data=new FormData();
      data.append("file",sourceFile,sourceFile.name);
      data.append("page",String(selected.page));
      data.append("width",String(selected.width));
      data.append("height",String(selected.height));
      data.append("polygon",JSON.stringify(selected.polygon));
      try {
        const response=await fetch("/api/review-crop",{method:"POST",body:data,signal:controller.signal});
        if(!response.ok){
          const payload=await response.json().catch(()=>({}));
          throw Error(payload.detail||"Không thể dựng crop từ file gốc.");
        }
        const blob=await response.blob();
        if(blob.type!=="image/png")throw Error("Backend không trả ảnh PNG.");
        if(live){objectURL=URL.createObjectURL(blob);setCrop(objectURL);}
      }catch(e){
        if(live&&e.name!=="AbortError")setCropError(e.message||String(e));
      }finally{if(live)setLoading(false);}
    }
    render();
    return ()=>{live=false;controller.abort();if(objectURL)URL.revokeObjectURL(objectURL);};
  },[selected?.review_key,result,sourceFile]);

  function saveNote(){
    if(!selected||!draft.trim()||draft.length>5000||/[\r\n]/.test(draft)){
      setFeedback("Chỉ nhập một dòng chữ đã nhìn thấy trong ảnh.");return;
    }
    setNotes(p=>({...p,[selected.review_key]:{
      page:selected.page,line_index:selected.line_index,ocr_original:selected.text,
      reviewed_text:draft,human_confirmed:true,is_changed:draft!==selected.text,
      reasons:selected.reasons,
    }}));
    setFeedback("Đã lưu phiên bản đối chiếu trong phiên làm việc. OCR gốc không đổi.");
  }
  function exportNotes(){
    downloadAudit((sourceFile?.name||"document").replace(/[^A-Za-z0-9._-]/g,"_")+"_number_review_only.json",{
      status:"LOCAL_EXPERIMENTAL_HUMAN_REVIEW_ONLY",
      source_filename:sourceFile?.name||"",
      original_ocr_unchanged:true,
      recognition_accuracy_not_claimed:true,
      automatic_text_replacement:false,
      saved_count:Object.keys(notes).length,
      alerts:candidates.map(c=>({...c,human_review:notes[c.review_key]||null})),
    });
  }

  return <section className="number-review-panel" aria-label="Thử nghiệm rà soát số văn bản">
    <header className="number-review-head">
      <div><FileSearch size={18}/><strong>Số văn bản cần kiểm tra</strong></div>
      <span>EXPERIMENTAL · CHỈ CẢNH BÁO</span>
    </header>
    <p className="number-review-desc">
      Cảnh báo dựa vào chuỗi OCR và vị trí dòng so với ngày ban hành ở trang đầu.
      Không sửa chữ VietOCR, không truy cập nhãn đúng và không cam kết phát hiện mọi lỗi.
      Chỉ tạo ghi chú xác minh riêng khi anh bấm lưu.
    </p>
    {!candidates.length ? <p className="number-review-clear">
      Không có cảnh báo theo quy tắc thử nghiệm. <strong>Chưa thể kết luận số văn bản đúng</strong>; hãy đối chiếu với PDF gốc.
    </p> : <>
      <p className="number-review-count"><AlertTriangle size={15}/> Có {candidates.length} trường hợp cần rà soát</p>
      <div className="number-review-items">
        {candidates.map((item,i)=><button key={item.review_key} type="button"
          className={i===chosen?"active":""} onClick={()=>{setChosen(i);setFeedback("");}}>
          {"Trang "+item.page+(item.line_index?", dòng "+item.line_index:" · chưa định vị")}
          {notes[item.review_key]?.human_confirmed?" ✓":""}
        </button>)}
      </div>
      {selected&&<div className="number-review-detail">
        <p><strong>Lý do cảnh báo:</strong> {selected.reasons.map(r=>REASONS[r]||r).join("; ")}</p>
        {selected.polygon ? <>
          <div className="number-review-crop">
            {loading?"Đang lấy ảnh gốc để đối chiếu...":crop?
              <img src={crop} alt="Vùng ảnh gốc chứa số văn bản; không phải ảnh VietOCR tự sửa"/>:
              <span>{"Chưa mở được ảnh crop. "+cropError+" Hãy xem PDF gốc ở cột trái."}</span>}
          </div>
          <label htmlFor="number-review-original">Chữ OCR nguyên bản (chỉ đọc)</label>
          <p id="number-review-original" className="number-review-original">{selected.text}</p>
          <label htmlFor="number-review-edit">Nội dung anh đọc được từ ảnh</label>
          <input id="number-review-edit" value={draft}
            onChange={e=>setDraft(e.target.value)} maxLength={5000}
            placeholder="Nhập đúng một dòng"/>
          <button type="button" className="number-review-save" onClick={saveNote}>
            <CheckCircle2 size={15}/> Lưu xác minh riêng, không sửa OCR
          </button>
        </> : <p>Không tìm thấy vùng ảnh đáng tin cậy. Hãy kiểm tra số văn bản trực tiếp trên trang 1 của PDF gốc; không tự suy đoán.</p>}
        {feedback&&<p className="number-review-feedback" role="status">{feedback}</p>}
      </div>}
      <button type="button" className="number-review-export"
        onClick={exportNotes}><Download size={15}/> {"Tải JSON rà soát riêng ("+Object.keys(notes).length+"/"+candidates.length+")"}</button>
    </>}
    <p className="number-review-warning">
      <Eye size={14}/> Các nút tải TXT/JSON OCR ở thanh công cụ vẫn xuất văn bản gốc.
      Kết quả xác minh chỉ nằm trong JSON riêng, không dùng để tính CER/WER.
    </p>
  </section>;
}

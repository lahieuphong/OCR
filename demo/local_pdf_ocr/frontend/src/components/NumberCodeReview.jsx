import {useEffect, useMemo, useRef, useState} from "react";
import {Button} from "@/components/ui/button";
import {findNumberReviewTargets, NUMBER_REVIEW_REASONS} from "@/lib/numberReview.js";
import "./NumberCodeReview.css";

/** The existing metadata input remains the only place to edit a code. */
export default function NumberCodeReview({result, sourceFile, disabled = false}) {
  const targets = useMemo(() => findNumberReviewTargets(result), [result]);
  const [choice, setChoice] = useState(null);
  const [preview, setPreview] = useState(null);
  const request = useRef(null), imageURL = useRef("");
  const index = choice?.result === result && choice?.file === sourceFile ? choice.index : 0;
  const selected = targets[index] || null;
  const current = preview?.result === result && preview?.file === sourceFile && preview?.key === selected?.review_key ? preview : null;

  function cancelPreview() {
    request.current?.abort(); request.current = null;
    if (imageURL.current) {URL.revokeObjectURL(imageURL.current); imageURL.current = "";}
  }
  useEffect(() => {
    setPreview(null); setChoice(null);
    return cancelPreview;
  }, [result, sourceFile, disabled]);

  async function showPreview() {
    if (disabled || !sourceFile || !selected?.polygon) return;
    cancelPreview();
    const controller = new AbortController(); request.current = controller;
    const context = {result, file: sourceFile, key: selected.review_key};
    setPreview({...context, phase: "loading"});
    const data = new FormData();
    data.append("file", sourceFile, sourceFile.name);
    data.append("page", String(selected.page));
    data.append("polygon", JSON.stringify(selected.polygon));
    data.append("render_width", String(selected.width));
    data.append("render_height", String(selected.height));
    try {
      const response = await fetch("/api/number-review/preview", {method: "POST", body: data, signal: controller.signal});
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(typeof payload.detail === "string" ? payload.detail : "Không thể mở vùng ảnh đối chiếu.");
      }
      const blob = await response.blob();
      if (blob.type !== "image/png") throw new Error("Ảnh đối chiếu trả về không hợp lệ.");
      if (request.current !== controller || controller.signal.aborted) return;
      const url = URL.createObjectURL(blob); imageURL.current = url;
      setPreview({...context, phase: "ready", url});
    } catch (error) {
      if (request.current === controller && !controller.signal.aborted) {
        setPreview({...context, phase: "error", error: error?.message || "Không thể mở vùng ảnh đối chiếu."});
      }
    } finally {if (request.current === controller) request.current = null;}
  }

  if (!result) return null;
  if (!["vietocr_ocr", "hybrid_h1"].includes(result.method) || result.used_ocr !== true) {
    return <p className="number-code-native-note">Đối chiếu số/ký hiệu với tài liệu gốc ở khung xem trước trước khi xác nhận.</p>;
  }
  return <section className="number-code-review" aria-label="Đối chiếu số và ký hiệu văn bản">
    <strong>Đối chiếu số/ký hiệu</strong>
    {!targets.length ? <p>Chưa có vùng ảnh đủ thông tin vị trí. Hãy xem trang 1 của tài liệu gốc.</p> : <>
      {targets.length > 1 && <div className="number-code-choices" aria-label="Các dòng số/ký hiệu">
        {targets.map((item, i) => <button type="button" key={item.review_key} disabled={disabled}
          aria-pressed={i === index} onClick={() => {cancelPreview(); setPreview(null); setChoice({result, file: sourceFile, index: i});}}>
          {item.line_index ? `Dòng ${item.line_index}` : "Chưa định vị"}{item.reasons.length ? " · cần kiểm tra" : ""}
        </button>)}
      </div>}
      {selected && <>
        {selected.reasons.length > 0 ? <ul className="number-code-warnings">{selected.reasons.map(reason => <li key={reason}>{NUMBER_REVIEW_REASONS[reason]}</li>)}</ul>
          : <p>Chưa thấy dấu hiệu bất thường theo quy tắc. Vẫn cần đối chiếu số/ký hiệu với ảnh gốc.</p>}
        {selected.text && <p className="number-code-original"><span>Văn bản nhận được:</span> <q>{selected.text}</q></p>}
        {selected.polygon ? <>
          <Button type="button" variant="outline" size="sm" disabled={disabled || !sourceFile || current?.phase === "loading"} onClick={showPreview}>
            {current?.phase === "loading" ? "Đang mở ảnh…" : "Xem ảnh đối chiếu"}
          </Button>
          {!sourceFile && <p>Chọn lại tài liệu gốc để mở ảnh đối chiếu.</p>}
        </> : <p>Chưa có vị trí đáng tin cậy để cắt ảnh. Hãy đối chiếu toàn bộ trang 1 ở khung xem trước.</p>}
        {current?.phase === "loading" && <p role="status">Đang dựng vùng ảnh từ tài liệu gốc.</p>}
        {current?.phase === "error" && <p role="alert">{current.error} Hãy xem tài liệu gốc ở khung xem trước.</p>}
        {current?.phase === "ready" && <figure><img src={current.url} alt={`Ảnh gốc đối chiếu số/ký hiệu, trang ${selected.page}${selected.line_index ? ` dòng ${selected.line_index}` : ""}`}/>
          <figcaption>Ảnh từ tài liệu gốc. Sửa Mã văn bản phía trên nếu cần rồi xác nhận giá trị đã kiểm tra.</figcaption></figure>}
      </>}
    </>}
  </section>;
}

import {memo, useEffect, useMemo, useRef, useState} from "react";
import {Search} from "lucide-react";
import {Button} from "@/components/ui/button";
import {BATCH_STATUS_LABELS} from "@/lib/documentBatch.js";
import {QUEUE_FILTERS, queueCounts, queueRows, subfolder, visibleRows} from "@/lib/documentQueue.js";

// Only what differs from the usual fast mode is written on a row, so a long list stays quiet.
const MODE_TAGS = {native_text:"Text có sẵn",vietocr_ocr:"OCR",hybrid_h1:"PDF + OCR"};
const STATUS_ON_ROW = new Set(["processing", "error"]);

// Memo plus the single click handler on the list: the timer re-renders the app while a document runs,
// and a list of up to 1000 rows must not redo its work each time.
const QueueRow = memo(function QueueRow({doc, index, status, active, working}) {
  const folder = subfolder(doc.path), label = BATCH_STATUS_LABELS[status];
  return <li data-id={doc.id} data-mode={doc.mode} className={active ? "active" : ""}>
    <button type="button" className="select-queued-file" title={doc.path || doc.name} aria-current={active ? "true" : undefined}>
      <span className="queue-index">{index + 1}</span>
      <i className={"queue-dot " + status} role="img" aria-label={label} title={label}/>
      <span className="queue-name">{doc.name}</span>
      {folder && <small className="queue-folder">{folder}</small>}
      <span className="queue-marks">
        {MODE_TAGS[doc.mode] && <span className="queue-tag">{MODE_TAGS[doc.mode]}</span>}
        {STATUS_ON_ROW.has(status) && <span className={"queue-status " + status}>{label}</span>}
      </span>
    </button>
    <button type="button" className="remove-document" aria-label={`Xóa tài liệu ${index + 1}: ${doc.name}`} title="Xóa khỏi danh sách" disabled={working}>×</button>
  </li>;
});

export default function DocumentQueue({documents, activeId, working, onSelect, onRemove}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const list = useRef(null);
  const rows = useMemo(() => queueRows(documents), [documents]);
  const counts = useMemo(() => queueCounts(rows), [rows]);
  const shown = useMemo(() => visibleRows(rows, {query, filter}), [rows, query, filter]);
  const filtered = Boolean(query.trim()) || filter !== "all";
  const clearFilters = () => {setQuery(""); setFilter("all");};

  // Follow the selected document (also while a batch advances), unless the pointer is on the list: never pull it away from the user.
  useEffect(() => {
    const box = list.current, row = box?.querySelector("li.active");
    if (!row || box.matches(":hover")) return;
    if (row.offsetTop < box.scrollTop) box.scrollTop = row.offsetTop;
    else if (row.offsetTop + row.offsetHeight > box.scrollTop + box.clientHeight) box.scrollTop = row.offsetTop + row.offsetHeight - box.clientHeight;
  }, [activeId, query, filter]);

  function clickList(event) {
    const id = event.target.closest("li[data-id]")?.dataset.id;
    if (!id) return;
    if (event.target.closest(".remove-document")) onRemove(id);
    else if (event.target.closest(".select-queued-file")) onSelect(id);
  }

  return <div className="input-queue">
    {(documents.length > 1 || filtered) && <div className="queue-toolbar">
      <label className="queue-search"><Search size={13}/>
        <input type="search" aria-label="Tìm tài liệu" placeholder="Tìm tên tệp, thư mục…" value={query} onChange={event => setQuery(event.target.value)}/>
      </label>
      <div className="queue-filters" role="group" aria-label="Lọc theo trạng thái">
        {QUEUE_FILTERS.filter(({key}) => key === "all" || counts[key] || filter === key).map(({key,label}) =>
          <button key={key} type="button" className={"queue-filter " + key} aria-pressed={filter === key} onClick={() => setFilter(key)}>
            {label}<b>{key === "all" ? rows.length : counts[key]}</b>
          </button>)}
      </div>
    </div>}
    {filtered && <div className="queue-summary" role="status">
      <span>Đang hiện {shown.length}/{rows.length} tài liệu. “Bóc tách tất cả” vẫn chạy cả danh sách.</span>
      <Button variant="ghost" size="sm" onClick={clearFilters}>Xóa bộ lọc</Button>
    </div>}
    {shown.length > 0 && <ol ref={list} onClick={clickList}>
      {shown.map(({doc,index,status}) => <QueueRow key={doc.id} doc={doc} index={index} status={status} active={doc.id === activeId} working={working}/>)}
    </ol>}
  </div>;
}

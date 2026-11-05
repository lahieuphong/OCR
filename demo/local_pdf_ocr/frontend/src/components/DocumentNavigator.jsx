import {ChevronLeft, ChevronRight} from "lucide-react";
import {Button} from "@/components/ui/button";
import {batchDocumentStatus, BATCH_STATUS_LABELS} from "@/lib/documentBatch.js";

// Switch between the listed documents from the result panel: previous / pick any / next.
// A select (not one chip per file) so that lists of hundreds of documents stay usable.
export default function DocumentNavigator({documents, activeId, onSelect}) {
  const index = documents.findIndex(doc => doc.id === activeId);
  if (documents.length < 2 || index < 0) return null;
  const go = offset => {
    const next = documents[index + offset];
    if (next) onSelect(next.id);
  };
  return <nav className="document-nav" aria-label="Chuyển tài liệu">
    <Button variant="outline" size="icon" aria-label="Tài liệu trước" title="Tài liệu trước" disabled={index === 0} onClick={() => go(-1)}><ChevronLeft size={16}/></Button>
    <select aria-label="Chọn tài liệu" value={activeId} onChange={event => onSelect(event.target.value)}>
      {documents.map((doc, i) => <option key={doc.id} value={doc.id}>
        {`File ${i + 1}/${documents.length} · ${doc.name} · ${BATCH_STATUS_LABELS[batchDocumentStatus(doc)]}`}
      </option>)}
    </select>
    <Button variant="outline" size="icon" aria-label="Tài liệu sau" title="Tài liệu sau" disabled={index === documents.length - 1} onClick={() => go(1)}><ChevronRight size={16}/></Button>
  </nav>;
}

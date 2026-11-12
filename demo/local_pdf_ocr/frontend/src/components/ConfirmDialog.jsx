import {useEffect, useId, useRef} from "react";
import {Check, X} from "lucide-react";
import {Button} from "@/components/ui/button";

// Both buttons carry an icon (docs/UI_ICONS.md): the caller picks the one of the action it confirms.
export default function ConfirmDialog({title, children, confirmLabel = "Tiếp tục", confirmIcon: ConfirmIcon = Check, onConfirm, onCancel}) {
  const ref = useRef(null);
  const id = useId();
  useEffect(() => {
    const dialog = ref.current;
    dialog.showModal();
    return () => { if (dialog.open) dialog.close(); };
  }, []);
  return <dialog className="confirm-dialog" ref={ref} role="alertdialog" aria-labelledby={id} aria-describedby={`${id}-description`}
    onCancel={event => {event.preventDefault(); onCancel();}}>
    <h2 id={id}>{title}</h2>
    <div id={`${id}-description`}>{children}</div>
    <div className="confirm-actions"><Button variant="outline" autoFocus onClick={onCancel}><X size={15}/>Hủy</Button><Button onClick={onConfirm}><ConfirmIcon size={15}/>{confirmLabel}</Button></div>
  </dialog>;
}

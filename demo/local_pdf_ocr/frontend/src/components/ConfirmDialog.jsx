import {useEffect, useId, useRef} from "react";
import {Button} from "@/components/ui/button";

export default function ConfirmDialog({title, children, confirmLabel = "Tiếp tục", onConfirm, onCancel}) {
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
    <div className="confirm-actions"><Button variant="outline" autoFocus onClick={onCancel}>Hủy</Button><Button onClick={onConfirm}>{confirmLabel}</Button></div>
  </dialog>;
}

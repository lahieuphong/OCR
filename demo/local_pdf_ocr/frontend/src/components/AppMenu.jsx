import {useEffect, useId, useLayoutEffect, useRef, useState} from "react";
import {createPortal} from "react-dom";
import {Activity, CircleCheck, FolderOpen, LoaderCircle, LogOut, Menu, Minus, Plus, RefreshCw, ScanText, TriangleAlert, X} from "lucide-react";
import {Button} from "@/components/ui/button";

// The desktop app's bridge (desktop/electron/preload-app.js); absent in a browser, where the menu is not shown.
export function desktopBridge() {
  return typeof window === "undefined" ? null : window.vietdocDesktop || null;
}

// The Windows title bar is part of the top bar (Window Controls Overlay): true while the system draws
// its minimise/maximise/close buttons over the page.
export function useWindowTitleBar() {
  const overlay = typeof navigator === "undefined" ? null : navigator.windowControlsOverlay;
  const [visible, setVisible] = useState(Boolean(overlay?.visible));
  useEffect(() => {
    if (!overlay) return;
    const update = () => setVisible(Boolean(overlay.visible));
    overlay.addEventListener?.("geometrychange", update);
    return () => overlay.removeEventListener?.("geometrychange", update);
  }, [overlay]);
  return visible;
}

// Under its button, right edges aligned, inside the window.
function placeUnder(button) {
  const rect = button.getBoundingClientRect();
  return {position:"fixed", top:rect.bottom + 6, right:Math.max(8, window.innerWidth - rect.right)};
}

function UpdateDialog({state, onClose}) {
  const ref = useRef(null), id = useId();
  useEffect(() => {
    const dialog = ref.current;
    dialog.showModal();
    return () => {if (dialog.open) dialog.close();};
  }, []);
  const checking = state === "checking", warning = state?.type === "warning";
  return <dialog className="confirm-dialog update-dialog" ref={ref} aria-labelledby={id} aria-busy={checking}
    onCancel={event => {event.preventDefault(); if (!checking) onClose();}}>
    <h2 id={id}>Cập nhật VietDoc OCR</h2>
    <p className={"update-message" + (warning ? " warning" : "")} role="status">
      {checking ? <LoaderCircle className="spin" size={16}/> : warning ? <TriangleAlert size={16}/> : <CircleCheck size={16}/>}
      <span>{checking ? "Đang kiểm tra bản mới trên GitHub…" : state.message}</span>
    </p>
    {state?.detail && <p className="update-detail">{state.detail}</p>}
    <div className="confirm-actions"><Button autoFocus disabled={checking} onClick={onClose}><X size={15}/>Đóng</Button></div>
  </dialog>;
}

// The app menu of the desktop app, in the page's top bar: it replaces the native menu bar ("VietDoc", "Xem"),
// which cannot follow the app's look. A WAI-ARIA menu button: arrows move, Escape closes, focus returns.
export default function AppMenu({bridge = desktopBridge()}) {
  const [info, setInfo] = useState(null);
  const [open, setOpen] = useState(false);
  const [zoom, setZoom] = useState(100);
  const [update, setUpdate] = useState(null);
  const [placement, setPlacement] = useState(null);
  const trigger = useRef(null), popup = useRef(null);
  const id = useId();

  useEffect(() => {
    let cancelled = false;
    bridge?.info().then(value => {if (!cancelled && value) {setInfo(value); setZoom(value.zoom ?? 100);}}).catch(() => {});
    return () => {cancelled = true;};
  }, [bridge]);
  useLayoutEffect(() => {
    if (open) popup.current?.querySelector("[role=menuitem]")?.focus();
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const outside = event => {if (!popup.current?.contains(event.target) && !trigger.current?.contains(event.target)) setOpen(false);};
    // The display size buttons resize the page under the open menu: it follows its button instead of closing.
    const follow = () => setPlacement(placeUnder(trigger.current));
    window.addEventListener("pointerdown", outside, true);
    window.addEventListener("resize", follow);
    return () => {window.removeEventListener("pointerdown", outside, true); window.removeEventListener("resize", follow);};
  }, [open]);
  if (!bridge || !info) return null;

  function show() {
    setPlacement(placeUnder(trigger.current));
    setOpen(true);
  }
  function close(returnFocus = true) {
    setOpen(false);
    if (returnFocus) trigger.current?.focus();
  }
  function run(action) {
    close(false);
    action();
  }
  async function changeZoom(step) {
    const value = await bridge.zoom(step);
    if (Number.isFinite(value)) setZoom(value);
  }
  async function checkUpdates() {
    setUpdate("checking");
    try {setUpdate(await bridge.checkUpdates() || {type:"warning", message:"Bản này không tự cập nhật."});}
    catch {setUpdate({type:"warning", message:"Không kiểm tra được bản cập nhật."});}
  }
  function keyDown(event) {
    const items = [...popup.current.querySelectorAll("[role=menuitem]:not(:disabled)")];
    const index = items.indexOf(document.activeElement);
    const moves = {ArrowDown:(index + 1) % items.length, ArrowUp:(index - 1 + items.length) % items.length, Home:0, End:items.length - 1};
    if (event.key in moves) {event.preventDefault(); items[moves[event.key]]?.focus();}
    else if (event.key === "Escape") {event.preventDefault(); event.stopPropagation(); close();}
    else if (event.key === "Tab") close(false);
  }

  const items = [
    {key:"status", icon:Activity, label:"Trạng thái hệ thống", hint:"Máy chủ xử lý và model OCR", action:() => bridge.openStatus()},
    {key:"logs", icon:FolderOpen, label:"Mở thư mục nhật ký", hint:"Gửi kèm khi báo lỗi", action:() => bridge.openLogs()},
    ...(info.updates ? [{key:"updates", icon:RefreshCw, label:"Kiểm tra cập nhật", hint:"Bản mới trên GitHub", action:checkUpdates}] : []),
  ];
  const item = ({key, icon: Icon, label, hint, action}) => <button key={key} type="button" role="menuitem" className="app-menu-item"
    data-action={key} onClick={() => run(action)}>
    <Icon size={16}/><span className="app-menu-text"><span>{label}</span>{hint && <small>{hint}</small>}</span>
  </button>;

  return <>
    <Button ref={trigger} variant="ghost" size="icon" className="app-menu-trigger" aria-label="Menu ứng dụng" title="Menu ứng dụng"
      aria-haspopup="menu" aria-expanded={open} aria-controls={open ? id : undefined}
      onClick={() => (open ? close() : show())}
      onKeyDown={event => {if (!open && ["ArrowDown", "Enter", " "].includes(event.key)) {event.preventDefault(); show();}}}>
      <Menu size={18}/>
    </Button>
    {open && createPortal(
      <div ref={popup} id={id} role="menu" aria-label="Menu ứng dụng" className="app-menu-content" style={placement} onKeyDown={keyDown}>
        <div className="app-menu-head" aria-hidden="true">
          <span className="app-menu-mark"><ScanText size={16} strokeWidth={1.8}/></span>
          <span><strong>VietDoc OCR</strong><small>Phiên bản {info.version}</small></span>
        </div>
        {items.map(item)}
        <div className="app-menu-separator" role="separator"/>
        <div className="app-menu-zoom" role="group" aria-label="Cỡ hiển thị">
          <span>Cỡ hiển thị</span>
          <span className="app-menu-zoom-buttons">
            <button type="button" role="menuitem" aria-label="Thu nhỏ" title="Thu nhỏ (Ctrl −)" onClick={() => changeZoom(-1)}><Minus size={14}/></button>
            <button type="button" role="menuitem" className="app-menu-zoom-value" aria-label={`Cỡ hiển thị ${zoom}%, bấm để về 100%`} title="Về cỡ mặc định (Ctrl 0)"
              onClick={() => changeZoom(0)}>{zoom}%</button>
            <button type="button" role="menuitem" aria-label="Phóng to" title="Phóng to (Ctrl +)" onClick={() => changeZoom(1)}><Plus size={14}/></button>
          </span>
        </div>
        <div className="app-menu-separator" role="separator"/>
        {item({key:"quit", icon:LogOut, label:"Thoát VietDoc OCR", action:() => bridge.quit()})}
      </div>, document.body)}
    {update && <UpdateDialog state={update} onClose={() => setUpdate(null)}/>}
  </>;
}

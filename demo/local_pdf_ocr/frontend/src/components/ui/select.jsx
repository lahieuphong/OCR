import {useEffect, useId, useLayoutEffect, useMemo, useRef, useState} from "react";
import {createPortal} from "react-dom";
import {Check, ChevronDown} from "lucide-react";
import {searchKey} from "@/lib/utils";

const MAX_POPUP_HEIGHT = 320, OPTION_HEIGHT = 30, MARGIN = 8, GAP = 4, TYPING_PAUSE_MS = 600;

// `widest` is the longest prefix of the list ("File 20/20"): every prefix takes its width, so the labels
// after "File 1/20" and "File 10/20" start in one column, in the list and in the trigger alike.
function fragments({prefix, label, hint, dot}, widest) {
  return <>
    {dot && <i className={"queue-dot " + dot}/>}
    {prefix && <span className="select-prefix" data-widest={widest}><span>{prefix}</span></span>}
    <span className="select-label">{label}</span>
    {hint && <span className="select-hint">{hint}</span>}
  </>;
}
const optionName = ({prefix, label, hint}) => [prefix, label, hint].filter(Boolean).join(" · ");

// Below the trigger when it fits, else on the side with more room, always inside the window.
function popupPlacement(trigger, minWidth, count) {
  const rect = trigger.getBoundingClientRect();
  const below = window.innerHeight - rect.bottom - MARGIN - GAP, above = rect.top - MARGIN - GAP;
  const up = below < Math.min(MAX_POPUP_HEIGHT, count * OPTION_HEIGHT + 10) && above > below;
  const width = Math.min(Math.max(rect.width, minWidth), window.innerWidth - 2 * MARGIN);
  return {position:"fixed", left:Math.max(MARGIN, Math.min(rect.left, window.innerWidth - width - MARGIN)), width,
    maxHeight:Math.min(MAX_POPUP_HEIGHT, up ? above : below),
    ...(up ? {bottom:window.innerHeight - rect.top + GAP} : {top:rect.bottom + GAP})};
}

// The app's own dropdown, instead of the browser's: same look on every system, and its options are only
// drawn while it is open, so a list of 1000 documents costs nothing the rest of the time.
// Options: {value, label, prefix?, hint?, dot?}. The trigger keeps keyboard focus throughout (WAI-ARIA select-only combobox).
export default function Select({options, value, onChange, placeholder = "", ariaLabel, popupMinWidth = 0, disabled, className = "", ...trigger}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [placement, setPlacement] = useState(null);
  const button = useRef(null), popup = useRef(null), typed = useRef({text:"",at:0});
  const id = useId();
  const selectedIndex = options.findIndex(option => option.value === value);
  const selected = options[selectedIndex];
  const widest = useMemo(() => options.reduce((longest, option) => (option.prefix?.length ?? 0) > longest.length ? option.prefix : longest, ""), [options]);

  function show(index = Math.max(selectedIndex, 0)) {
    if (disabled || !options.length) return;
    setPlacement(popupPlacement(button.current, popupMinWidth, options.length));
    setActive(index); setOpen(true);
    button.current.focus({preventScroll:true});
  }
  function choose(index) {
    setOpen(false);
    if (options[index] && options[index].value !== value) onChange(options[index].value);
  }
  // Letters jump to the next option with a word starting with them, accents ignored: "vi" finds "Vĩnh viễn".
  function typeahead(character, from) {
    const now = Date.now();
    const text = (now - typed.current.at < TYPING_PAUSE_MS ? typed.current.text : "") + searchKey(character);
    typed.current = {text, at:now};
    const start = text.length === 1 ? from + 1 : from;
    for (let step = 0; step < options.length; step++) {
      const index = (start + step) % options.length;
      if ((" " + searchKey(options[index].label)).includes(" " + text)) return index;
    }
    return from;
  }
  function keyDown(event) {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const typing = event.key.length === 1 && (event.key !== " " || Date.now() - typed.current.at < TYPING_PAUSE_MS);
    if (!open) {
      if (typing) {event.preventDefault(); show(typeahead(event.key, Math.max(selectedIndex, 0)));}
      else if (["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) {event.preventDefault(); show();}
      return;
    }
    const last = options.length - 1;
    const moves = {ArrowDown:Math.min(active + 1, last), ArrowUp:Math.max(active - 1, 0), Home:0, End:last,
      PageDown:Math.min(active + 10, last), PageUp:Math.max(active - 10, 0)};
    if (event.key in moves) {event.preventDefault(); setActive(moves[event.key]);}
    else if (typing) {event.preventDefault(); setActive(typeahead(event.key, active));}
    else if (event.key === "Enter" || event.key === " ") {event.preventDefault(); choose(active);}
    else if (event.key === "Escape") {event.preventDefault(); event.stopPropagation(); setOpen(false);}
  }

  useLayoutEffect(() => {
    if (open) popup.current?.children[active]?.scrollIntoView({block:"nearest"});
  }, [open, active]);
  useEffect(() => {
    if (!open) return;
    // Anchored to the trigger: moving the page under it closes it, as a native dropdown does.
    const close = event => {if (!popup.current?.contains(event.target)) setOpen(false);};
    window.addEventListener("resize", close);
    window.addEventListener("scroll", close, true);
    return () => {window.removeEventListener("resize", close); window.removeEventListener("scroll", close, true);};
  }, [open]);
  useEffect(() => {if (disabled) setOpen(false);}, [disabled]);

  return <>
    <button {...trigger} ref={button} type="button" role="combobox" value={value} disabled={disabled} aria-label={ariaLabel} aria-haspopup="listbox" aria-expanded={open}
      aria-controls={open ? id : undefined} aria-activedescendant={open ? `${id}-${active}` : undefined} className={("select-trigger " + className).trim()}
      onClick={() => {if (open) setOpen(false); else show();}} onKeyDown={keyDown} onBlur={() => setOpen(false)}>
      <span className={"select-value" + (selected || value ? "" : " placeholder")}>{selected ? fragments(selected, widest) : <span className="select-label">{value || placeholder}</span>}</span>
      <ChevronDown className="select-chevron" size={14}/>
    </button>
    {open && createPortal(
      // Pressing here must not take focus from the trigger: its blur closes the list before the click lands.
      <ul ref={popup} id={id} role="listbox" aria-label={ariaLabel} className="select-content" style={placement} onMouseDown={event => event.preventDefault()}>
        {options.map((option, index) => <li key={option.value} id={`${id}-${index}`} role="option" aria-selected={index === selectedIndex} aria-label={optionName(option)} title={optionName(option)} data-value={option.value}
          className={"select-option" + (index === active ? " active" : "") + (index === selectedIndex ? " selected" : "")}
          onMouseMove={() => setActive(index)} onClick={() => choose(index)}>
          {fragments(option, widest)}
          {/* The tick keeps its slot on every row, so the hints form one column. */}
          <span className="select-check">{index === selectedIndex && <Check size={14}/>}</span>
        </li>)}
      </ul>, document.body)}
  </>;
}

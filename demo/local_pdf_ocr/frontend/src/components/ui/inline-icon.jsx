// An icon inside a sentence ("bấm <icon> để xác nhận"): the same lucide icon as the button the sentence
// names, never a character standing in for it (docs/UI_ICONS.md). Screen readers hear the label instead.
export default function InlineIcon({icon: Icon, label}) {
  return <span className="inline-icon"><Icon size={12} aria-hidden="true"/><span className="sr-only">{label}</span></span>;
}

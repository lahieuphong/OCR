import {CircleCheck, TriangleAlert} from "lucide-react";

// The icon of a coloured status label (docs/UI_ICONS.md): "Cần kiểm tra" and "Lỗi" warn, "Đã xác nhận" is done.
// Neutral states (Chưa xử lý, Đang xử lý, Đã bóc tách) stay text only.
const ICONS = {review: TriangleAlert, error: TriangleAlert, confirmed: CircleCheck};

export default function StatusIcon({status, size = 11}) {
  const Icon = ICONS[status];
  return Icon ? <Icon size={size} className="status-icon" aria-hidden="true"/> : null;
}

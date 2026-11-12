# Quy tắc icon của giao diện VietDoc OCR

Áp dụng cho giao diện web (`demo/local_pdf_ocr/frontend`) và các cửa sổ riêng của app desktop: cửa sổ **Trạng thái hệ thống** (`desktop/electron/status.html`) và màn hình khởi động (`desktop/electron/lib/splash.js`).

## Quy tắc

1. **Chỉ dùng một bộ icon: [lucide](https://lucide.dev)** (giấy phép ISC, đã có trong `THIRD_PARTY_NOTICES`).
   - Giao diện web: import từ `lucide-react`.
   - Cửa sổ desktop: chép đúng SVG của lucide vào HTML và ghi tên icon ở `data-lucide`.
   - Không dùng emoji, ảnh icon hay bộ icon khác.
2. **Mọi nút đều có icon.**
   - Nút có chữ: icon đứng trước chữ, ví dụ `<X size={14}/> Đóng`.
   - Nút chỉ có icon: bắt buộc có `aria-label` và nên có `title`.
3. **Mọi mục mở/đóng (`<summary>`) có icon lucide**, thường là `ChevronRight` hoặc `ChevronDown`, và ẩn tam giác mặc định của trình duyệt.
4. **Không dùng ký tự thay icon**, như ×, ✓, ☰, ⚠, ▸, ▾. Nếu câu chữ nhắc tới một nút (ví dụ "bấm ✓ để xác nhận"), hiển thị đúng icon của nút đó bằng `components/ui/inline-icon.jsx`.
5. **Cùng một hành động dùng cùng một icon ở mọi nơi.**

   | Hành động | Icon |
   |---|---|
   | Đóng, Hủy, Xóa khỏi danh sách | `X` |
   | Thêm tệp, Chọn tài liệu | `UploadCloud` |
   | Thư mục, Mở thư mục nhật ký | `FolderOpen` |
   | Đổi tệp | `Replace` |
   | Bóc tách lại, Thử lại, Khởi động lại máy chủ | `RotateCcw` |
   | Xác nhận | `Check` |
   | Tải JSON/TXT | `Download` |
   | Sao chép | `Copy` |
   | Xuất Excel | `FileSpreadsheet` |
   | Đang chạy | `LoaderCircle` (xoay, lớp `spin`) |
   | Xong | `CircleCheck` |
   | Cảnh báo, lỗi | `TriangleAlert` / `AlertTriangle` |
   | Thoát | `LogOut` |
   | Xử lý trên máy | `LockKeyhole` |

   Kích thước icon trong nút từ 13 đến 18 px, nét mặc định 2. Riêng biểu tượng ứng dụng (`ScanText`) dùng nét 1,7.

## Ngoại lệ: control mà nhãn chính là giá trị

Các control dưới đây giữ dạng chữ, vì nhãn của chúng chính là giá trị được chọn, không phải một hành động. Danh sách này nằm ở `TEXT_ONLY_CONTROLS` trong `frontend/src/test/iconRule.js`. Muốn thêm ngoại lệ thì sửa ở đó, kèm lý do.

| Control | Ví dụ |
|---|---|
| Lựa chọn trong ô chọn (`[role=option]`) | `01 · Vĩnh viễn` |
| Một dòng của danh sách tài liệu | `1 ● tên tệp.pdf` |
| Tên tài liệu dạng liên kết trong bảng | `12/QĐ-UBND` |
| Nút lọc theo trạng thái kèm số lượng | `Lỗi 2` |
| Số trang | `Trang 1` |
| Dòng số/ký hiệu | `Dòng 3` |
| Cỡ hiển thị trong menu ☰ | `100%` |

## Cách quy tắc được kiểm tra

- **Mọi test giao diện web** (`npm test` trong `frontend`): sau mỗi test, `src/test/setup.js` quét màn hình vừa dựng. Test sẽ fail nếu có nút hoặc `<summary>` thiếu icon lucide, nút chỉ có icon mà thiếu `aria-label`, hoặc nút dùng ký tự thay icon.
- **`src/test/iconRule.test.jsx`** kiểm tra ba việc:
  - không file `.jsx` nào dùng ký tự thay icon;
  - mọi nút và mục mở/đóng của cửa sổ Trạng thái hệ thống đều có icon;
  - mọi SVG có `data-lucide` trong cửa sổ Trạng thái và màn hình khởi động khớp từng nét với icon cùng tên của `lucide-react`.
- **Smoke test của app thật** (`desktop/scripts/check-smoke-report.js`):
  - màn hình 22 trường không được có nút nào thiếu icon;
  - cửa sổ Trạng thái hệ thống phải có icon ở mọi nút.

## Thêm icon vào cửa sổ desktop

Cửa sổ desktop không dùng React, nên SVG được chép tay:

1. Mở `frontend/node_modules/lucide-react/dist/esm/icons/<tên-icon>.js` và chép các phần tử `path`, `circle`, `rect`, `line`, `polyline` vào một `<svg>`.
2. Đặt các thuộc tính sau cho `<svg>`:
   - `class="lucide"` và `data-lucide="<tên-icon>"`;
   - `viewBox="0 0 24 24"`, `fill="none"`, `stroke="currentColor"`;
   - `stroke-linecap="round"`, `stroke-linejoin="round"`;
   - `aria-hidden="true"`.
3. Chạy `npm test` trong `frontend`. Nếu chép sai một nét, test đối chiếu sẽ chỉ ra icon đó.

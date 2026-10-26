# VietDoc OCR

Ứng dụng desktop nhận dạng tiếng Việt từ PDF, PNG và JPG, hỗ trợ thông tin văn bản 22 trường và xuất Excel 23 cột. Tài liệu được xử lý trên máy, không gửi tới dịch vụ OCR bên ngoài.

## Hai bản cài đặt hiện có

| Nền tảng | File cài đặt | Ghi chú |
|---|---|---|
| Windows x64 | `VietDoc OCR Setup.exe` — 24/10/2026 | Installer offline có model OCR, được chia sẻ riêng trong nội bộ. |
| macOS 15+ · Apple Silicon | `VietDoc-OCR-0.1.0-macOS-arm64.dmg` — 26/10/2026 | [Tải bản Mac](https://github.com/lahieuphong/OCR/actions/workflows/vietdoc-macos.yml), cần chép model OCR riêng. Không hỗ trợ Mac Intel. |

Bản Windows hiện có chưa được build lại theo các cập nhật metadata/Excel mới nhất trên `main`.

## Cài đặt và sử dụng

- **Windows:** chạy `VietDoc OCR Setup.exe`, cài đặt rồi mở VietDoc OCR.
- **Mac:** chọn lần build thành công mới nhất ở link trên, tải artifact **VietDoc-OCR-macOS-arm64** và giải nén. Mở DMG, kéo app vào **Applications**. Nếu macOS chặn bản test, chọn **Privacy & Security → Open Anyway**.
- Chọn file, dùng **Text có sẵn trong PDF** hoặc **OCR bằng VietOCR B**, kiểm tra kết quả rồi xuất TXT, JSON hoặc Excel.

Bản Mac đọc được PDF có text và xuất Excel khi chưa có model. Để OCR ảnh/scan, làm theo [hướng dẫn cấu hình model trên Mac](packaging/macos/README.md). Máy dùng bản cài đặt không cần cài Python hay Node.js.

## Mã nguồn và phát triển

Code ứng dụng hiện hành ở nhánh **`main`**:

- [Frontend/backend](demo/local_pdf_ocr/README.md) — giao diện, xử lý tài liệu và OCR.
- [Electron](desktop/README.md) — chạy ứng dụng từ source, cấu hình và kiểm thử.
- [Đóng gói](packaging/README.md) · [Build Mac](packaging/macos/README.md) · [Các nhánh nghiên cứu](docs/BRANCHES.md).

Model, dữ liệu riêng tư và file cài đặt được giữ ngoài Git. Đây là các bản test nội bộ; [điều kiện phát hành cộng đồng](release/README.md) chưa hoàn tất.

# VietDoc OCR

Ứng dụng desktop nhận dạng tiếng Việt từ PDF, PNG và JPG, hỗ trợ thông tin văn bản 22 trường và xuất Excel 23 cột. Tài liệu được xử lý trên máy, không gửi tới dịch vụ OCR bên ngoài.

## Hai bản tải về

| Nền tảng | File cài đặt | Tải về |
|---|---|---|
| Windows 10/11 x64 | `VietDoc-OCR-0.1.0-Windows-x64-Setup.exe` | [Tải bản Windows](https://github.com/lahieuphong/OCR/actions/workflows/vietdoc-packaging-ci.yml) |
| macOS 15+ · Apple Silicon | `VietDoc-OCR-0.1.0-macOS-arm64.dmg` | [Tải bản Mac](https://github.com/lahieuphong/OCR/actions/workflows/vietdoc-macos.yml) |

Cả hai bản tải từ GitHub đều cần **chép model OCR riêng**. PDF có text và xuất Excel dùng được ngay khi chưa có model. Bản Mac không hỗ trợ Intel.

## Cài đặt và sử dụng

- **Windows:** chọn lần chạy thành công có gói **VietDoc-OCR-Windows-x64**, tải và giải nén rồi chạy `.exe`. App có tên **VietDoc OCR Test**, cài đặt và lưu cấu hình riêng để giữ nguyên bản offline cũ có model.
- **Mac:** chọn lần chạy thành công có gói **VietDoc-OCR-macOS-arm64**, tải và giải nén. Mở DMG, kéo app vào **Applications**. Nếu macOS chặn bản test, chọn **Privacy & Security → Open Anyway**.
- Chọn file, dùng **Text có sẵn trong PDF** hoặc **OCR bằng VietOCR B**, kiểm tra kết quả rồi xuất TXT, JSON hoặc Excel.

Máy dùng bản cài đặt không cần cài Python hay Node.js. Hướng dẫn model: [Windows](packaging/windows/README.md) · [Mac](packaging/macos/README.md). Gói tải trên GitHub được giữ 30 ngày; có thể chạy lại workflow để tạo bản mới.

## Mã nguồn và phát triển

Code ứng dụng hiện hành ở nhánh **`main`**:

- [Frontend/backend](demo/local_pdf_ocr/README.md) — giao diện, xử lý tài liệu và OCR.
- [Electron](desktop/README.md) — chạy ứng dụng từ source, cấu hình và kiểm thử.
- [Đóng gói](packaging/README.md) · [Build Mac](packaging/macos/README.md) · [Các nhánh nghiên cứu](docs/BRANCHES.md).

Model, dữ liệu riêng tư và file cài đặt được giữ ngoài Git. Đây là các bản test nội bộ; [điều kiện phát hành cộng đồng](release/README.md) chưa hoàn tất.

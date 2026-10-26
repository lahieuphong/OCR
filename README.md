# VietDoc OCR

Ứng dụng desktop nhận dạng tiếng Việt từ PDF, PNG và JPG, hỗ trợ thông tin văn bản 22 trường và xuất Excel 23 cột. Tài liệu được xử lý trên máy, không gửi tới dịch vụ OCR bên ngoài.

## Hai bản tải về

| Nền tảng | File cài đặt | Tải về |
|---|---|---|
| Windows 10/11 x64 | `VietDoc-OCR-0.1.0-Windows-x64-Setup.exe` | [Tải Windows (.zip)](https://github.com/lahieuphong/OCR/actions/runs/40294105270/artifacts/12637299322) |
| macOS 15+ · Apple Silicon | `VietDoc-OCR-0.1.0-macOS-arm64.dmg` | [Tải Mac (.zip)](https://github.com/lahieuphong/OCR/actions/runs/40294105172/artifacts/12637792703) |

**Cần đăng nhập GitHub bằng tài khoản có quyền truy cập repo.** Nút tải trả về ZIP; giải nén để lấy file cài đặt. Hai link còn hiệu lực đến **25/11/2026**.

**Bản tải hiện tại:** commit [`8a56503`](https://github.com/lahieuphong/OCR/commit/8a56503bf88bf45dbfed55e975dd1c589d615939), ngày 26/10/2026. Chưa có tính năng đối chiếu số/ký hiệu và H1 mới trên `main`; chưa có gói cài mới build thành công.

Cả hai bản tải từ GitHub đều cần **chép model OCR riêng**. PDF có text và xuất Excel dùng được ngay khi chưa có model. Bản Mac không hỗ trợ Intel.

## Cài đặt và sử dụng

- **Windows:** tải ZIP ở bảng trên, giải nén rồi chạy `.exe`. App có tên **VietDoc OCR Test**, cài đặt và lưu cấu hình riêng để giữ nguyên bản offline cũ có model.
- **Mac:** tải và giải nén ZIP ở bảng trên. Mở DMG, kéo app vào **Applications**. Nếu macOS chặn bản test, chọn **Privacy & Security → Open Anyway**.
- Chọn file, dùng **Text có sẵn trong PDF** hoặc **OCR bằng VietOCR B**, kiểm tra kết quả rồi xuất TXT, JSON hoặc Excel.

Máy dùng bản cài đặt không cần cài Python hay Node.js. Hướng dẫn model: [Windows](packaging/windows/README.md) · [Mac](packaging/macos/README.md). Khi link hết hạn, cần build thành công gói mới từ workflow [Windows](https://github.com/lahieuphong/OCR/actions/workflows/vietdoc-packaging-ci.yml) / [Mac](https://github.com/lahieuphong/OCR/actions/workflows/vietdoc-macos.yml).

## Mã nguồn và phát triển

Code ứng dụng hiện hành ở nhánh **`main`**:

Source đã có **Đối chiếu số/ký hiệu → Xem ảnh đối chiếu** và **Kết hợp PDF + OCR (thử nghiệm)**. H1 cần model, chỉ chạy khi chọn riêng và giữ OCR gốc để so sánh. [Hướng dẫn tính năng mới](docs/OCR_REVIEW_AND_H1.md).

- [Frontend/backend](demo/local_pdf_ocr/README.md) — giao diện, xử lý tài liệu và OCR.
- [Electron](desktop/README.md) — chạy ứng dụng từ source, cấu hình và kiểm thử.
- [Đóng gói](packaging/README.md) · [Build Mac](packaging/macos/README.md) · [Các nhánh nghiên cứu](docs/BRANCHES.md).

Model, dữ liệu riêng tư và file cài đặt được giữ ngoài Git. Đây là các bản test nội bộ; [điều kiện phát hành cộng đồng](release/README.md) chưa hoàn tất.

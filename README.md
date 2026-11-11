# VietDoc OCR

Ứng dụng desktop nhận dạng tiếng Việt từ PDF, PNG và JPG, hỗ trợ thông tin văn bản 22 trường và xuất Excel 23 cột. Tài liệu được xử lý trên máy, không gửi tới dịch vụ OCR bên ngoài.

## Tải về

**Windows 10 (1903 trở lên) / Windows 11, 64-bit:** vào [trang phát hành mới nhất](https://github.com/lahieuphong/OCR/releases/latest).

- **Setup (khuyên dùng):** `VietDoc-OCR-v<phiên bản>-Windows-x64-Setup.exe`. Cài cho tài khoản hiện tại, có lối tắt Start Menu, tự cập nhật từ GitHub Releases.
- **Portable:** `VietDoc-OCR-v<phiên bản>-Windows-x64-Portable.zip`. Giải nén rồi chạy `VietDoc OCR\VietDoc OCR.exe`; không tự cập nhật.

Hai bản đều có sẵn model OCR, không cần Python, Node.js hay Git. Kiểm tra file tải về bằng `SHA256SUMS.txt`. Bản build chưa ký số. Hướng dẫn: [release/windows/HUONG_DAN_CAI_DAT.md](release/windows/HUONG_DAN_CAI_DAT.md).

**macOS 15+ (Apple Silicon):** chỉ có bản test không kèm model, build qua workflow [Mac](https://github.com/lahieuphong/OCR/actions/workflows/vietdoc-macos.yml) (cần chép model riêng, xem [packaging/macos/README.md](packaging/macos/README.md)).

Chọn file hoặc cả thư mục, bấm **Bóc tách nhanh** để lấy 22 trường thông tin từ trang 1, kiểm tra kết quả rồi xuất JSON hoặc Excel. Tài liệu được xử lý trên máy, không gửi tới dịch vụ OCR bên ngoài.

## Mã nguồn và phát triển

Code ứng dụng hiện hành ở nhánh **`main`**:

Giao diện chỉ còn **Bóc tách nhanh**. Backend vẫn giữ các chế độ đọc lớp chữ PDF, OCR toàn văn và **Kết hợp PDF + OCR (thử nghiệm)** để kiểm thử và đánh giá, nhưng giao diện không gọi tới chúng ([ghi chú](docs/OCR_REVIEW_AND_H1.md)).

- [Frontend/backend](demo/local_pdf_ocr/README.md) — giao diện, xử lý tài liệu và OCR.
- [Electron](desktop/README.md) — chạy ứng dụng từ source, cấu hình và kiểm thử.
- [Đóng gói](packaging/README.md) · [Build Mac](packaging/macos/README.md) · [Các nhánh nghiên cứu](docs/BRANCHES.md).

Model, dữ liệu riêng tư và file cài đặt được giữ ngoài Git. Quy trình phát hành và hồ sơ giấy phép (đang rà soát): [release/PHAT_HANH_WINDOWS.md](release/PHAT_HANH_WINDOWS.md), [release/GIAY_PHEP_PHUONG_AN.md](release/GIAY_PHEP_PHUONG_AN.md).

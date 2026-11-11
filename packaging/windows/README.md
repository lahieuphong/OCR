# VietDoc OCR Test — Windows x64

Bộ cài `.exe` chứa Electron, giao diện và backend; máy test không cần cài Python hay Node.js. Yêu cầu Windows 10/11 x64. Đây là bản test nội bộ, chưa ký số.

## Tải và cài

1. Mở [workflow Windows](https://github.com/lahieuphong/OCR/actions/workflows/vietdoc-packaging-ci.yml), chọn lần chạy thành công mới nhất có artifact **VietDoc-OCR-Windows-x64**.
2. Tải artifact, giải nén và kiểm SHA-256 theo `SHA256SUMS.txt` trước khi mở file `VietDoc-OCR-0.1.0-Windows-x64-Setup.exe`.
3. Chạy bộ cài rồi mở **VietDoc OCR Test** từ Start Menu. Bản cài chỉ dành cho tài khoản hiện tại, không yêu cầu quyền quản trị.

Bản **Test** có thư mục cài, shortcut và cấu hình riêng, có thể giữ song song với bản offline cũ có model. Không thay thế các file model của bản cũ.

## Sử dụng

Chọn PDF, PNG hoặc JPG. PDF có text và xuất Excel dùng được ngay. OCR ảnh/scan cần bộ model riêng; ứng dụng không tải model tự động.

Chép model đã xác minh vào thư mục riêng, giữ nguyên cấu trúc:

```
<modelRoot>/vietocr/onnx/exp_b_width1024/{encoder.onnx,decoder_step.onnx,metadata.json,parity_full.json}
<modelRoot>/vietocr/finetuned/exp_b_width1024/weights.pth
<paddlexHome>/official_models/PP-OCRv6_medium_det/{inference.json,inference.pdiparams,inference.yml}
```

Mở app một lần rồi thoát. Tạo `%APPDATA%\VietDoc OCR Test\desktop.config.json` với đường dẫn thực tế trên máy:

```json
{
  "modelRoot": "C:\\VietDoc\\models",
  "paddlexHome": "C:\\VietDoc\\paddlex"
}
```

Thư mục PaddleX phải ghi được và nằm ngoài thư mục cài app. Mở lại app, bấm nút menu **☰** ở góc phải thanh trên cùng → **Trạng thái hệ thống**. Thiếu file hoặc sai SHA-256 sẽ khóa OCR.

## Lưu dữ liệu app cạnh thư mục cài

Mặc định cấu hình, log và bộ nhớ trình duyệt của app nằm trong `%APPDATA%\<tên app>`. Muốn giữ tất cả cạnh bản cài, tạo thư mục `<tên app> Data` ngay bên cạnh thư mục cài trước khi mở app, ví dụ cài bằng `"VietDoc OCR Setup.exe" /S /D=E:\VietDoc\VietDoc OCR` rồi tạo `E:\VietDoc\VietDoc OCR Data`. Bản Test dùng `VietDoc OCR Test Data`. Khi thư mục này tồn tại, `desktop.config.json` đặt trong đó thay cho `%APPDATA%`. Gỡ hoặc cài lại app không xóa thư mục này. Dữ liệu cũ trong `%APPDATA%` không tự chuyển sang.

Model không có trong artifact tải từ GitHub. Bản offline nội bộ có model vẫn được giữ riêng; các [điều kiện phát hành cộng đồng](../../release/README.md) vẫn áp dụng.

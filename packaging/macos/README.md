# VietDoc OCR — bản test macOS Apple Silicon

Yêu cầu: Mac M1/M2/M3/M4/M5, macOS 15 trở lên. Không dùng bản này cho Intel.
Bản DMG chứa Electron, giao diện và Python backend native arm64; máy test không cần cài Node.js/Python.

## Tải và mở

1. Mở GitHub → Actions → **VietDoc macOS DMG (Apple Silicon)** → **Run workflow** để build một bản mới, rồi mở lần chạy đó khi đã xong. Lần chạy tự động sau mỗi push/PR vẫn kiểm tra DMG nhưng không lưu file để tải.
2. Tải artifact **VietDoc-OCR-macOS-arm64**, giải nén. Chạy `shasum -a 256 -c SHA256SUMS.txt` tại thư mục đó để kiểm tra file.
3. Mở `.dmg`, kéo **VietDoc OCR.app** vào **Applications**, eject ổ đĩa rồi mở app trong Applications.

Đây là bản test nội bộ, ký ad-hoc, chưa có Developer ID/notarization. macOS có thể chặn lần mở đầu.
Sau khi đã kiểm tra nguồn tải và checksum, vào **System Settings → Privacy & Security → Open Anyway** để cho phép đúng app này.
Không tắt Gatekeeper của hệ thống.

## Test khi chưa có model

App vẫn mở và đọc **văn bản có sẵn trong PDF**, điền/sửa metadata 22 trường, xử lý nhiều tài liệu và xuất XLSX 23 cột.
Thử copy/paste bằng Cmd+C/Cmd+V, đổi kích thước cửa sổ, mở PDF/PNG/JPG, xuất Excel, đóng rồi mở lại.
OCR ảnh/scan bị khóa rõ ràng khi thiếu model; app không tải model tự động.

## Bật OCR bằng model đã có

Model riêng không được đưa vào Git, artifact CI hay DMG tải từ GitHub. Sao chép bộ model đã xác minh từ máy Windows sang Mac qua kênh riêng.
Giữ nguyên cấu trúc:

```
<modelRoot>/vietocr/onnx/exp_b_width1024/{encoder.onnx,decoder_step.onnx,metadata.json,parity_full.json}
<modelRoot>/vietocr/finetuned/exp_b_width1024/weights.pth
<paddlexHome>/official_models/PP-OCRv6_medium_det/{inference.json,inference.pdiparams,inference.yml}
```

Mở app một lần, thoát app. Tạo file
`~/Library/Application Support/VietDoc OCR/desktop.config.json` với đường dẫn tuyệt đối thực tế trên Mac:

```json
{
  "modelRoot": "/Users/yourname/VietDoc/models",
  "paddlexHome": "/Users/yourname/VietDoc/paddlex"
}
```

Muốn giữ cấu hình, log và bộ nhớ trình duyệt cạnh app thay vì `~/Library/Application Support`, tạo thư mục `VietDoc OCR Data` ngay cạnh `VietDoc OCR.app` (ví dụ `/Applications/VietDoc OCR Data`) trước khi mở app; khi đó đặt `desktop.config.json` trong thư mục này.
Thư mục PaddleX phải ghi được, nằm ngoài `.app` và DMG. Mở lại app, chọn menu **VietDoc → Trạng thái backend và model**.
Backend kiểm SHA-256 cũ trước khi cho phép OCR. Không thay weights hoặc bỏ kiểm SHA để vượt lỗi.
Chỉ dùng tài liệu DEV để test; so kết quả scan với nhãn được người đọc độc lập. CI chưa xác nhận độ chính xác OCR thật trên Mac.

## Tự build trên Mac

Workflow `.github/workflows/vietdoc-macos.yml` ghi đầy đủ các bước tạo venv riêng, cài wheel PaddlePaddle 3.2.0 từ CPU index chính thức,
cài `packaging/backend/requirements-macos.txt`, PaddleOCR vendored và hai npm lockfile.
Sau khi cài dependency, đặt `VPY` là Python venv và `OUT` là thư mục tuyệt đối ngoài checkout, rồi chạy:

```bash
bash packaging/macos/build.sh
```

Build chạy unit tests, production build, đóng gói backend native bằng PyInstaller, kiểm chữ ký ad-hoc/fuses,
scan file riêng tư, probe backend (token/Host/Origin/loopback), smoke app trên đường dẫn Unicode,
đọc PDF, xuất/đọc lại XLSX, crash/restart/shutdown và kiểm DMG đã mount read-only.
Chỉ DMG release được upload; bản smoke có quyền tự động hóa chỉ tồn tại trên runner.
Artifact tải được giữ 7 ngày, chỉ tạo khi bấm **Run workflow**, không tạo public GitHub Release. Các gate phát hành cộng đồng trong `release/` vẫn áp dụng.

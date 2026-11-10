# VietDoc OCR — ma trận QA community release

**Kế hoạch, chưa phải phép thử đã chạy.** GitHub CI hiện model-free. Ghi machine/Windows/CPU/RAM, SHA256 installer, log, kết quả vào folder **ngoài Git**, chỉ dùng dữ liệu công khai/synthetic/được phép. Không đọc blind 30.signed.pdf.

| Trường hợp | PASS khi | Tình trạng |
| --- | --- | --- |
| Windows 11 sạch x64, không Python/Node/Git/model cache | NSIS install standard user, launch, OCR, TXT/JSON, uninstall | CHƯA THỬ |
| Windows 10 sạch x64 | Tương tự, không phải cài thêm runtime | CHƯA THỬ |
| Firewall chặn outbound | Install/OCR PDF+PNG offline, không kết nối ra ngoài | CHƯA THỬ |
| PDF text layer, PDF scan nhiều trang | Kết quả theo baseline non-blind | CHƯA THỬ VM |
| PNG/JPG/Unicode/đường dẫn dấu/cách | OCR, clipboard, UTF-8 TXT/JSON | CHƯA THỬ VM |
| File lỗi, giả extension, >15MB, >6 trang, >12MP | Bị từ chối có kiểm soát | CHƯA THỬ ĐỦ |
| Xóa/sửa ONNX/weights/detector | OCR fail-closed, không model download | CHƯA THỬ VM |
| Restart, crash, đóng app, reboot | Không sót process/port/token | CHƯA THỬ VM |
| Windows N/KN, CPU không AVX, thiếu VC++ runtime | Hỗ trợ hoặc công bố giới hạn rõ ràng | CHƯA THỬ |
| RAM thấp, xử lý lặp nhiều lần | Đo peak RAM/performance, không hỏng dữ liệu | CHƯA THỬ |
| SmartScreen/Defender/code signing | Authenticode Valid, không tắt bảo vệ | CHƯA THỬ |
| Bundle/historical secrets và privacy scan | Không có tài liệu nhạy cảm/weights vô ý | CHƯA THỬ ĐỦ |
| License/SBOM/corresponding source | Quyền phân phối được duyệt | BLOCKED |
| Setup v0.1.0: cài không hỏi và có giao diện, Start Menu, Desktop tùy chọn, mở lại, cài đè (nâng cấp), gỡ | Payload = thư mục app đã kiểm tra; dữ liệu người dùng còn sau nâng cấp và gỡ; không còn bản sao installer trong `%LOCALAPPDATA%` | Có công cụ (`packaging/windows`); kết quả ghi ngoài Git |
| Portable ZIP: giải nén bằng Explorer/`Expand-Archive`, chạy, đóng | File = thư mục app đã kiểm tra; dữ liệu nằm trong `VietDoc OCR Data`, không ghi `%APPDATA%\VietDoc OCR`; không còn tiến trình | Có công cụ; kết quả ghi ngoài Git |
| Thư mục cài hoặc giải nén có dấu tiếng Việt và khoảng trắng (code page 1252) | OCR chạy nhờ manifest `activeCodePage` UTF-8 của backend | Có công cụ; Windows 10 trước 1903 không hỗ trợ |
| Đường dẫn dài (tài khoản 20 ký tự, giải nén trong Downloads) | ≤ 259 ký tự, `build_release.py` kiểm tra khi build | Tự động trong build |

Báo cáo từ máy dev: 10333 50/50 và 137 255/255 khớp A0; 383 129/129 khớp DEV; PNG/JPG 38/38 khớp DEV. **Scan 383 trang 4 khác A0 ở thứ tự 5 dòng chữ ký**. Không được ghi là A0-perfect.

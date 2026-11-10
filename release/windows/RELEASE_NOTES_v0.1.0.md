# VietDoc OCR v0.1.0 cho Windows

**Ngày phát hành:** `<YYYY-MM-DD>` · **Mã nguồn:** commit `<40 ký tự>` · **Chữ ký số:** chưa có (UNSIGNED)

<!-- Điền các ô <…> từ BUILD_INFO.txt và SHA256SUMS.txt của đúng bản build đã qua kiểm định, rồi xóa dòng này. -->

VietDoc OCR nhận dạng chữ tiếng Việt trong PDF, PNG và JPG, đọc 22 trường thông tin văn bản hành chính và xuất TXT, JSON, Excel. Ứng dụng chạy hoàn toàn trên máy: không gửi tài liệu lên Internet, không tải model, không tự cập nhật. Không cần cài Python, Node.js hay Git.

## Tải về

| File | Dùng khi | Kích thước |
|---|---|---|
| `VietDoc-OCR-v0.1.0-Windows-x64-Setup.exe` | Cài cho tài khoản hiện tại (khuyên dùng) | `<… MB>` |
| `VietDoc-OCR-v0.1.0-Windows-x64-Portable.zip` | Giải nén rồi chạy, không cài | `<… MB>` |
| `SHA256SUMS.txt` | Kiểm tra file tải về | |
| `BUILD_INFO.txt` | Phiên bản, commit nguồn, model, trạng thái ký số | |
| `HUONG_DAN_CAI_DAT.md` | Hướng dẫn đầy đủ | |
| `THIRD_PARTY_NOTICES.txt` | Thông báo giấy phép bên thứ ba | |
| `<mã nguồn tương ứng>` | Theo nghĩa vụ giấy phép | `<…>` |

## Tính năng chính

- **Bóc tách nhanh** 22 trường từ trang 1: số và ký hiệu, ngày ban hành, cơ quan ban hành, loại văn bản, trích yếu, dấu đỏ… Ô không chắc chắn được để trống hoặc đánh dấu **Cần kiểm tra**; chữ số viết tay không đọc được sẽ không bị đoán.
- **Nhận dạng OCR** cho bản scan và ảnh chụp (VietOCR B1024 và bộ phát hiện dòng chữ PP-OCRv6), chạy bằng CPU.
- **Text có sẵn**: đọc lớp chữ của PDF điện tử mà không OCR.
- Văn bản hợp nhất (VBHN): lấy số, ngày và cơ quan từ khối "XÁC THỰC VĂN BẢN HỢP NHẤT" khi trang 1 không có.
- Phát hiện dấu đỏ tròn từ màu ảnh; loại trừ hình in hai màu đỏ và vàng như quốc huy.
- Xử lý cả thư mục theo hàng đợi, tạm dừng và tiếp tục; xuất Excel 23 cột cho nhiều văn bản.

## Thay đổi mới

Đây là bản phát hành đầu tiên dạng **Setup** và **Portable** có sẵn model OCR: tải về là dùng được ngay, không phải chép model riêng như các bản thử nghiệm trước.

## Yêu cầu

Windows 10 phiên bản 1903 trở lên hoặc Windows 11, 64-bit (x64). Khoảng 2 GB dung lượng trống; nên có từ 8 GB RAM. Không hỗ trợ Windows 32-bit hay ARM. Thư mục cài đặt và thư mục giải nén có thể có tên tiếng Việt.

## Cài đặt

- **Setup:** chạy file `…-Setup.exe` → **I Agree** → chọn lối tắt Desktop nếu muốn → **Install**. Cài vào `%LOCALAPPDATA%\Programs\VietDoc OCR`, không cần quyền quản trị. Gỡ trong Settings → Apps.
- **Portable:** chuột phải file ZIP → **Extract All…** → mở `VietDoc OCR\VietDoc OCR.exe`. Dữ liệu được lưu trong thư mục `VietDoc OCR Data` cạnh ứng dụng.

Xem chi tiết trong `HUONG_DAN_CAI_DAT.md`.

## Kiểm tra SHA-256

Tải `SHA256SUMS.txt` vào cùng thư mục, mở PowerShell tại đó:

```powershell
Get-Content .\SHA256SUMS.txt | ForEach-Object {
  $hash, $name = $_ -split '\s+', 2
  if ((Get-FileHash -LiteralPath $name -Algorithm SHA256).Hash -eq $hash) { "KHỚP   $name" } else { "SAI    $name" }
}
```

Bản build chưa có chữ ký số. Nếu Windows SmartScreen cảnh báo, chỉ chọn **More info → Run anyway** khi SHA-256 khớp. Không tắt SmartScreen hay Microsoft Defender.

## Giới hạn đã biết

- Chưa ký số; SmartScreen có thể cảnh báo.
- Tối đa 15 MB mỗi tệp; Nhận dạng OCR tối đa 6 trang mỗi PDF; ảnh tối đa 12 megapixel. OCR bằng CPU: mỗi trang scan có thể mất vài chục giây.
- Chữ số viết tay (số văn bản, ngày ký) có thể không đọc được; khi đó ô được để trống với trạng thái **Cần kiểm tra**.
- Một số trường không in trên văn bản không được điền tự động.
- Không có cập nhật tự động: tải và cài phiên bản mới bằng tay.
- `<Kết quả kiểm thử trên Windows 10 và Windows 11 sạch: điền trước khi phát hành.>`

## Giấy phép và mã nguồn

`<Giấy phép của VietDoc OCR và cách nhận mã nguồn tương ứng: điền sau khi chủ dự án hoàn tất rà soát giấy phép (release/LICENSING_AUDIT.md).>` Thông báo giấy phép của các thành phần bên thứ ba có trong `THIRD_PARTY_NOTICES.txt` và trong thư mục `resources\licenses` của ứng dụng.

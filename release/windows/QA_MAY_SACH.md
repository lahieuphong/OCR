# Kiểm thử VietDoc OCR trên Windows sạch

Quy trình cho người kiểm thử bản Setup và Portable trước khi phát hành. Mỗi mục chỉ ghi **PASS** khi có bằng chứng (ảnh chụp, file kết quả, log). Mục không chạy được thì ghi **NOT TESTED**, kèm lý do.

## 1. Máy thử

| Máy | Yêu cầu |
|---|---|
| Windows 10 x64 | Phiên bản 1903 trở lên (gõ `winver`), mới cài hoặc VM snapshot sạch |
| Windows 11 x64 | Mới cài, hoặc Windows Sandbox (mục 4) |

Trên cả hai máy:
- chưa từng cài Python, Node.js, Git hay VietOCR;
- không có thư mục `%USERPROFILE%\.paddlex`;
- không có `%APPDATA%\VietDoc OCR`;
- ngắt mạng (rút cáp, tắt Wi-Fi hoặc chặn bằng tường lửa) trước khi cài.

Tạo thêm một tài khoản Windows chuẩn (không phải quản trị) có tên tiếng Việt, ví dụ `Nguyễn Văn Thử`, để thử mục 3.9.

Chép vào máy: Setup, Portable ZIP, `SHA256SUMS.txt`, và bộ tài liệu thử gồm một PDF có lớp chữ, một PDF scan đen trắng, một PDF scan màu, một PNG, một JPG. Chỉ dùng tài liệu được phép, không dùng dữ liệu blind.

## 2. Ghi lại môi trường

Mở PowerShell và lưu kết quả:

```powershell
winver
Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber
(Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Nls\CodePage').ACP
foreach ($t in 'python','py','node','npm','git') { "$t = $((Get-Command $t -ErrorAction SilentlyContinue).Source)" }
Test-Path "$env:USERPROFILE\.paddlex"; Test-Path "$env:APPDATA\VietDoc OCR"
Get-NetAdapter | Where-Object Status -eq 'Up'
```

## 3. Danh sách kiểm thử

| # | Bước | PASS khi |
|---|---|---|
| 3.1 | Kiểm tra SHA-256 theo `HUONG_DAN_CAI_DAT.md` | Hai file đều `KHỚP` |
| 3.2 | Chạy Setup bằng giao diện: I Agree → **chọn** "Tạo lối tắt trên Desktop" → Install → Finish | Không hỏi quyền quản trị; có lối tắt Start Menu **và** Desktop; Apps có "VietDoc OCR" |
| 3.3 | Mở ứng dụng từ lối tắt Desktop | Một cửa sổ, thanh trên cùng nền trắng liền với nút thu nhỏ/phóng to/đóng, không có thanh menu tối; nút **☰ → Trạng thái hệ thống** báo model đã kiểm tra, OCR được phép |
| 3.4 | Bóc tách nhanh (cách xử lý duy nhất của app): PDF có lớp chữ, PDF scan đen trắng, PDF scan màu, PNG, JPG | Có kết quả, không báo lỗi, không cần mạng; không có ô chọn phương pháp |
| 3.5 | Bóc tách nhanh 22 trường trên ít nhất 3 văn bản; xuất JSON, TXT, Excel | JSON có đủ 22 khóa; Excel mở được, đủ 23 cột |
| 3.6 | Kiểm tra `%APPDATA%\VietDoc OCR` | Thư mục được tạo, có `logs\`; không có file nào trong thư mục cài ngoài `resources\paddlex\{func_ret,locks,temp}` rỗng |
| 3.7 | Đóng ứng dụng, mở Task Manager | Không còn `VietDoc OCR.exe` hay `vietdoc-backend.exe` |
| 3.8 | Mở lại, OCR một tài liệu, đóng | Như 3.3–3.7 |
| 3.9 | Đăng nhập tài khoản `Nguyễn Văn Thử`, cài Setup, OCR PDF scan và PNG | OCR chạy (đường dẫn cài là `C:\Users\Nguyễn Văn Thử\AppData\Local\Programs\VietDoc OCR`) |
| 3.10 | Portable: Extract All vào `Desktop\Thư mục Portable có dấu ă`, chạy `VietDoc OCR\VietDoc OCR.exe`, OCR PDF scan và JPG | OCR chạy; dữ liệu nằm trong `VietDoc OCR Data`; `%APPDATA%\VietDoc OCR` không đổi |
| 3.11 | Cài đè Setup (nâng cấp) khi `%APPDATA%\VietDoc OCR` đã có dữ liệu | Dữ liệu còn nguyên; ứng dụng mở được |
| 3.12 | Gỡ cài đặt từ Settings → Apps | Thư mục cài, lối tắt Start Menu và Desktop bị xóa; `%APPDATA%\VietDoc OCR` còn; không còn tiến trình |
| 3.13 | Xung đột hồ sơ: mở bản cài, rồi mở bản Portable đã đổi tên `VietDoc OCR Data` (để nó dùng chung `%APPDATA%`) | Bản thứ hai không mở backend thứ hai mà thoát hoặc chuyển sang cửa sổ đang mở |
| 3.14 | Windows SmartScreen khi mở Setup tải từ Internet | Ghi lại thông báo; chỉ "Run anyway" sau khi SHA-256 khớp; không tắt Defender hay SmartScreen |

Bản DEV (`Chay_VietDoc.cmd`) dùng chung `%APPDATA%\VietDoc OCR` với bản cài. Mục 3.13 kiểm tra đúng tình huống đó bằng hai bản đóng gói, vì máy sạch không có Python.

## 4. Chạy tự động trong Windows Sandbox

Windows 11 Pro/Enterprise có tính năng **Windows Sandbox**: máy ảo sạch, có thể ngắt mạng, bị xóa khi đóng. Sandbox chạy cùng phiên bản Windows với máy chủ, nên **không thay thế được bài thử Windows 10**.

Các script trong `packaging/windows/clean_machine/` tự làm các mục 3.1–3.4, 3.6–3.13 bên trong sandbox:

- cài bằng chính giao diện NSIS (bấm nút qua thông điệp Windows, chụp từng trang), có chọn lối tắt Desktop;
- OCR qua backend của bản đã cài;
- mở/đóng ứng dụng;
- cài đè, Portable ở thư mục có dấu, xung đột hồ sơ;
- tạo tài khoản `Nguyễn Văn Thử` rồi cài và OCR dưới tài khoản đó;
- gỡ cài đặt.

1. Sửa 4 đường dẫn `HostFolder` trong `vdqa.wsb.template`, lưu thành `vdqa.wsb`:
   - thư mục `release` của bản build (chỉ đọc);
   - thư mục tài liệu thử (chỉ đọc);
   - thư mục script này (chỉ đọc);
   - một thư mục kết quả trống.
2. Tạo `sandbox_docs.txt` cạnh các script: mỗi dòng `<tên file>=<chế độ>`.
3. Mở `vdqa.wsb`. Sandbox chạy khoảng 25–40 phút rồi tự tắt. Muốn chạy lại vài bước, thêm `-Only <bước>,<bước>` sau `run_sandbox_qa.ps1` trong `LogonCommand`, ví dụ `-Only environment,gui_install,upgrade_silent_reinstall,upgrade_gui_reinstall,uninstall`. Kết quả nằm ở thư mục kết quả: `results.json`, `gui_*.png`, `ocr_*` và `vn_out`.
4. So OCR với bản chạy từ mã nguồn:

   ```
   python packaging\windows\clean_machine\compare_sandbox.py <thư mục kết quả> <thư mục tham chiếu của check_packaged_ocr.py --dev-python>
   ```

Hai bước tùy chọn:

- **`ui_smoke`**: làm mục 3.5 bằng biến thể smoke nội bộ của cùng bản build: OCR qua giao diện, xuất TXT, JSON, Excel. Cần gắn thêm `C:\vd\smoke` và `C:\vd\fixtures` (xem `vdqa.wsb.template`). Kiểm kết quả trên máy chủ bằng `desktop/scripts/check-smoke-report.js --expect=ocr --with-pdf --with-fast` và `desktop/scripts/check_excel_export.py`.
  - Script chép ứng dụng sang một thư mục ghi được trước khi chạy, vì PaddleX ghi `temp`, `locks`, `func_ret` vào `resources\paddlex`.
  - Nếu chạy trực tiếp từ thư mục chỉ đọc, OCR báo lỗi. Đây là giới hạn đã biết của bản hiện tại.
- **`smartscreen_probe`**: gắn dấu "tải từ Internet" lên một bản sao Setup rồi mở, chụp hộp thoại SmartScreen. Sandbox tắt mạng, nên chỉ thấy hành vi khi offline. Mục 3.14 khi có mạng vẫn cần người làm.

## 5. Mẫu báo cáo

Mỗi mục ghi: máy (Windows 10/11, build), PASS / FAIL / NOT TESTED, bằng chứng (tên file), ghi chú. Nộp kèm SHA-256 của Setup và ZIP đã thử, để gắn vào `release/check_release_candidate.py` (nhóm `qa`).

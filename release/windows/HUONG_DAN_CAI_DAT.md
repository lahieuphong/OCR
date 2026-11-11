# VietDoc OCR cho Windows: cài đặt và sử dụng

VietDoc OCR nhận dạng chữ tiếng Việt trong PDF, PNG và JPG, đọc 22 trường thông tin văn bản và xuất TXT, JSON, Excel. Mọi xử lý chạy trên máy của bạn: ứng dụng không gửi tài liệu lên Internet và không tải model. Bản Setup tự kiểm tra và cài bản mới từ GitHub Releases; bản Portable không tự cập nhật. Máy không cần Python, Node.js hay Git.

## 1. Chọn bản tải

| | Setup (khuyên dùng) | Portable |
|---|---|---|
| File | `VietDoc-OCR-v<phiên bản>-Windows-x64-Setup.exe` | `VietDoc-OCR-v<phiên bản>-Windows-x64-Portable.zip` |
| Cách dùng | Cài cho tài khoản Windows hiện tại | Giải nén rồi chạy, không cài |
| Quyền quản trị | Không cần | Không cần |
| Lối tắt | Start Menu; Desktop nếu bạn chọn | Không tạo |
| Cập nhật | Tự động từ GitHub Releases | Tải bản mới bằng tay |
| Gỡ bỏ | Settings → Apps | Xóa thư mục |
| Dữ liệu ứng dụng | `%APPDATA%\VietDoc OCR` | Thư mục `VietDoc OCR Data` cạnh ứng dụng |

Cả hai bản có cùng chức năng và cùng model OCR. Chọn Portable khi không muốn cài, ví dụ chạy từ ổ USB hoặc máy dùng chung.

## 2. Yêu cầu

- Windows 10 phiên bản 1903 trở lên hoặc Windows 11, 64-bit (x64). Không hỗ trợ Windows 32-bit hay Windows trên ARM.
- Khoảng 2 GB dung lượng trống. Nên có từ 8 GB RAM.
- Không cần Internet sau khi đã tải về.

## 3. Kiểm tra file tải về (SHA-256)

Mỗi bản phát hành có file `SHA256SUMS.txt`. Tải nó vào cùng thư mục với file cài đặt, mở PowerShell trong thư mục đó và chạy:

```powershell
Get-Content .\SHA256SUMS.txt | ForEach-Object {
  $hash, $name = $_ -split '\s+', 2
  if ((Get-FileHash -LiteralPath $name -Algorithm SHA256).Hash -eq $hash) { "KHỚP   $name" } else { "SAI    $name" }
}
```

Chỉ dùng file có kết quả `KHỚP`. Cách khác: `certutil -hashfile <tên file> SHA256` rồi so với dòng tương ứng trong `SHA256SUMS.txt`. Nếu không khớp, xóa file và tải lại từ trang phát hành.

## 4. Chữ ký số và cảnh báo của Windows

Bản phát hành hiện **chưa có chữ ký số** (UNSIGNED). Khi mở, Windows SmartScreen có thể hiện "Windows protected your PC".

- Chỉ tiếp tục khi bạn đã tải file từ trang phát hành chính thức của dự án và SHA-256 khớp (mục 3). Khi đó bấm **More info → Run anyway** cho riêng file này.
- Không tắt SmartScreen, Microsoft Defender hay phần mềm diệt virus để chạy VietDoc OCR.

## 5. Cài bằng Setup

1. Chạy file `…-Setup.exe`.
2. Đọc trang thông báo, bấm **I Agree**.
3. Chọn có tạo lối tắt trên Desktop hay không. Lối tắt trong Start Menu luôn được tạo.
4. Bấm **Install**, rồi **Finish**. Ứng dụng tự mở nếu ô "Run VietDoc OCR" được chọn.

Ứng dụng được cài vào `%LOCALAPPDATA%\Programs\VietDoc OCR`, chỉ cho tài khoản hiện tại.

**Cập nhật:** khi có Internet, ứng dụng tự kiểm tra GitHub Releases sau khi mở, tải bản mới ở nền và cài khi bạn đóng ứng dụng. Bạn cũng có thể bấm nút menu **☰** ở góc phải thanh trên cùng → **Kiểm tra cập nhật**, hoặc tự chạy Setup của phiên bản mới. Cài đặt, nhật ký và lối tắt Desktop được giữ lại.

**Gỡ bỏ:** Settings → Apps → Installed apps → **VietDoc OCR** → Uninstall. Thư mục `%APPDATA%\VietDoc OCR` vẫn được giữ; xóa thủ công nếu không cần nữa.

**Cài không hỏi (cho người quản trị máy):** `…-Setup.exe /S`, không tạo lối tắt Desktop. Thêm `/D=<thư mục>` ở cuối dòng lệnh để chọn nơi cài. Nếu tạo sẵn thư mục `VietDoc OCR Data` ngay cạnh thư mục cài (ví dụ cài vào `D:\VietDoc\VietDoc OCR` và tạo `D:\VietDoc\VietDoc OCR Data`), dữ liệu ứng dụng sẽ được lưu ở đó thay vì `%APPDATA%`.

## 6. Dùng bản Portable

1. Bấm chuột phải vào file ZIP → **Extract All…**, chọn một thư mục mà tài khoản của bạn có quyền ghi, ví dụ `D:\VietDoc`. Không mở ứng dụng ngay trong cửa sổ xem ZIP. Không giải nén vào `C:\Program Files`.
2. Mở thư mục `VietDoc OCR` và chạy `VietDoc OCR.exe`.
3. Giữ thư mục `VietDoc OCR Data` cạnh thư mục `VietDoc OCR`: cài đặt, nhật ký và dữ liệu trình duyệt của bản Portable nằm ở đó.
4. Để gỡ, đóng ứng dụng rồi xóa cả hai thư mục.

## 7. Sử dụng

1. Bấm chọn tệp, kéo thả tệp hoặc chọn cả thư mục (PDF, PNG, JPG).
2. Bấm **Bóc tách nhanh văn bản này**, hoặc **Bóc tách tất cả** khi có nhiều tệp. Ứng dụng đọc 22 trường thông tin từ trang 1: dùng lớp chữ của PDF điện tử khi có, còn bản scan và ảnh chụp thì OCR phần đầu trang.
3. Kiểm tra kết quả. Ô nào ghi **Cần kiểm tra** phải được người dùng xác nhận.
4. Xuất JSON 22 trường hoặc Excel (nhiều văn bản trong một bảng). Nội dung phần đầu trang đã đọc có thể tải dạng TXT hoặc JSON.

Giới hạn: tối đa 15 MB mỗi tệp; chỉ đọc trang 1 của PDF; ảnh tối đa 12 megapixel. OCR chạy bằng CPU nên mỗi bản scan có thể mất vài giây đến vài chục giây.

## 8. Quyền riêng tư

- Tài liệu chỉ được xử lý trên máy. Phần xử lý OCR chỉ nghe kết nối nội bộ (127.0.0.1) và từ chối mọi yêu cầu không mang mã của ứng dụng.
- Không thu thập dữ liệu sử dụng, không tải model. Bản Setup chỉ kết nối GitHub để kiểm tra và tải bản cập nhật của chính VietDoc OCR (file `latest.yml`, kiểm tra SHA-512 trước khi cài). Bản Portable không kết nối Internet.
- Kết quả chỉ được ghi ra đĩa khi bạn bấm xuất và chọn nơi lưu.

## 9. Khi gặp sự cố

- Nút menu **☰** ở góc phải thanh trên cùng → **Trạng thái hệ thống** cho biết model đã được kiểm tra chưa. Nếu báo thiếu hoặc sai SHA-256 thì OCR bị khóa: cài lại hoặc giải nén lại bản Portable.
- Nút menu **☰ → Mở thư mục nhật ký** mở nhật ký để gửi kèm khi báo lỗi. Nhật ký ghi trạng thái và lỗi, có thể chứa đường dẫn thư mục trên máy (kể cả tên tài khoản Windows); hãy xem lại trước khi gửi.

## 10. Giấy phép

Thông báo giấy phép của các thành phần bên thứ ba nằm trong `resources\licenses\THIRD_PARTY_NOTICES.txt` của thư mục ứng dụng. Giấy phép của Electron và Chromium nằm cạnh `VietDoc OCR.exe` (`LICENSE.electron.txt`, `LICENSES.chromium.html`).

# VietDoc OCR v0.1.2 cho Windows

Commit nguồn, model và trạng thái ký số của bản build: xem `BUILD_INFO.txt`. Kiểm tra file tải về bằng `SHA256SUMS.txt`.

## Thay đổi mới

- Bỏ thanh menu tối "VietDoc · Xem". Thanh trên cùng của ứng dụng giờ là thanh tiêu đề: nền trắng liền khối với nút thu nhỏ, phóng to, đóng, và vẫn kéo được cửa sổ.
- Nút menu **☰** ở góc phải gom các chức năng: **Trạng thái hệ thống**, **Mở thư mục nhật ký**, **Kiểm tra cập nhật**, **Cỡ hiển thị** (− 100% +) và **Thoát**. Phím tắt Ctrl +, Ctrl − và Ctrl 0 vẫn dùng được.
- Kết quả kiểm tra cập nhật hiện ngay trong ứng dụng.
- Đã bỏ "Tải lại" vì bấm nhầm sẽ mất danh sách tài liệu đang làm.
- Cửa sổ **Trạng thái hệ thống** có giao diện đồng bộ với ứng dụng và chỉ nói về Bóc tách nhanh: PDF có lớp chữ, bản scan và ảnh (OCR).
- Máy đã cài bản Setup tự tải bản này và cài khi đóng ứng dụng. Bản Portable cần tải lại bằng tay.

## Tính năng chính

- **Bóc tách nhanh** 22 trường từ trang 1: số và ký hiệu, ngày ban hành, cơ quan ban hành, loại văn bản, trích yếu, dấu đỏ… Ô không chắc chắn được để trống hoặc đánh dấu **Cần kiểm tra**. Chữ số viết tay không đọc được thì không đoán.
- Tự dùng lớp chữ của PDF điện tử khi có. Với bản scan và ảnh chụp, ứng dụng OCR phần đầu trang.
- Xử lý cả thư mục theo hàng đợi, có tạm dừng và tiếp tục. Xuất Excel 23 cột cho nhiều văn bản, hoặc JSON 22 trường cho từng văn bản.
- Xử lý ngay trên máy: không gửi tài liệu lên Internet, không tải model. Kết nối mạng duy nhất là bước kiểm tra cập nhật của bản Setup.

## Yêu cầu

Windows 10 phiên bản 1903 trở lên hoặc Windows 11, 64-bit (x64). Khoảng 2 GB dung lượng trống, nên có từ 8 GB RAM.

## Giới hạn đã biết

- Chưa ký số, nên SmartScreen có thể cảnh báo. Chỉ chọn **More info → Run anyway** khi SHA-256 khớp.
- Tối đa 15 MB mỗi tệp và chỉ đọc trang 1 của PDF. Ảnh tối đa 12 megapixel. OCR bằng CPU: mỗi bản scan có thể mất vài giây đến vài chục giây.
- Chữ số viết tay có thể không đọc được. Khi đó ô được để trống với trạng thái **Cần kiểm tra**.
- Chưa kiểm thử trên Windows 10.

Hướng dẫn cài đặt: `HUONG_DAN_CAI_DAT.md`. Thông báo giấy phép bên thứ ba: `THIRD_PARTY_NOTICES.txt`.

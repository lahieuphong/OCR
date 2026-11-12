# VietDoc OCR v0.1.3 cho Windows

Commit nguồn, model và trạng thái ký số của bản build: xem `BUILD_INFO.txt`. Kiểm tra file tải về bằng `SHA256SUMS.txt`.

## Thay đổi mới

- Form 22 trường gọn hơn: không còn đoạn giải thích dài dưới từng ô. Nhãn **Cần kiểm tra** có icon cảnh báo màu vàng; rê chuột lên nhãn để xem lý do.
- Mọi nút đều có icon, cùng một kiểu trong toàn ứng dụng, kể cả cửa sổ **Trạng thái hệ thống** và màn hình khởi động. Nút xóa tài liệu khỏi danh sách dùng icon thay cho dấu ×.
- Nhãn trạng thái **Đang xử lý**, **Cần kiểm tra**, **Lỗi** và **Đã xác nhận** có icon ở form 22 trường, bảng **Danh sách văn bản** và danh sách tài liệu.
- Cửa sổ **Trạng thái hệ thống** hiện icon theo tình trạng: đang khởi động, sẵn sàng, thiếu model hoặc lỗi.
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

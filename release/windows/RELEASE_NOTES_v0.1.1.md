# VietDoc OCR v0.1.1 cho Windows

Commit nguồn, model và trạng thái ký số của bản build: xem `BUILD_INFO.txt`. Kiểm tra file tải về bằng `SHA256SUMS.txt`.

## Thay đổi mới

- Giao diện chỉ còn một cách xử lý là **Bóc tách nhanh**: đọc 22 trường thông tin từ trang 1 của mỗi tài liệu. Đã bỏ các nút **Text có sẵn**, **Nhận dạng OCR**, **PDF + OCR** cùng ô "Áp dụng cho cả N tài liệu", nên không còn bước chọn phương pháp.
- Bóc tách nhanh tự dùng lớp chữ của PDF điện tử khi có. Với bản scan và ảnh chụp, ứng dụng OCR phần đầu trang. PDF dài hơn 6 trang vẫn xử lý được vì chỉ đọc trang 1.
- Đã bỏ tab "So sánh" và các nút xuất toàn văn. Phần đầu trang đã đọc vẫn tải được dạng TXT hoặc JSON, ghi rõ là nội dung một phần.
- Nút "Xem ảnh đối chiếu" số/ký hiệu trước đây chỉ có ở chế độ OCR nên không còn. Hãy đối chiếu số/ký hiệu với tài liệu gốc ở khung xem trước.
- Máy đã cài bản Setup v0.1.0 tự tải bản này và cài khi đóng ứng dụng. Bản Portable cần tải lại bằng tay.

## Tính năng chính

- **Bóc tách nhanh** 22 trường: số và ký hiệu, ngày ban hành, cơ quan ban hành, loại văn bản, trích yếu, dấu đỏ… Ô không chắc chắn được để trống hoặc đánh dấu **Cần kiểm tra**. Chữ số viết tay không đọc được thì không đoán.
- Văn bản hợp nhất (VBHN): lấy số, ngày và cơ quan từ khối "XÁC THỰC VĂN BẢN HỢP NHẤT" khi trang 1 không có.
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

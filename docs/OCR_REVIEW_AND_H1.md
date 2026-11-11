# Đối chiếu số/ký hiệu và PDF + OCR thử nghiệm

> **Cập nhật 2026-11-11:** giao diện ứng dụng chỉ còn **Bóc tách nhanh**. Các nút Text có sẵn, Nhận dạng OCR và PDF + OCR đã được gỡ khỏi giao diện, nên hai tính năng dưới đây hiện không mở được từ app: Bóc tách nhanh không có nút **Xem ảnh đối chiếu** và hướng dẫn người dùng đối chiếu với tài liệu gốc ở khung xem trước. Backend vẫn giữ các chế độ `native_text`, `vietocr_ocr`, `hybrid_h1` và API ảnh đối chiếu cho kiểm thử và đánh giá. Nội dung bên dưới mô tả hành vi trước thay đổi này.

## Đối chiếu dữ liệu trước khi xuất

Sau khi nhận dạng, mở **Thông tin văn bản → Mã văn bản**. Phần **Đối chiếu số/ký hiệu** cảnh báo chữ lẫn trong số, chữ số bị cách hoặc thiếu tiền tố ở vùng đầu trang. Đây là dấu hiệu cần kiểm tra, không phải kết luận dữ liệu sai hay điểm tin cậy OCR.

Nhấn **Xem ảnh đối chiếu** để xem vùng ảnh nguồn. Sửa **Mã văn bản** trong ô hiện có rồi xác nhận; Số tài liệu và Ký hiệu văn bản cập nhật theo giá trị đó. Nếu không định vị được vùng ảnh, xem toàn bộ trang 1 ở khung tài liệu gốc. Chế độ đọc text PDF chỉ hướng dẫn xem bản gốc.

Ảnh được dựng khi người dùng yêu cầu, không chạy OCR lần nữa hoặc lưu tài liệu. Đổi tài liệu/kết quả sẽ hủy yêu cầu ảnh và bỏ ảnh cũ. Cảnh báo không tự sửa văn bản hoặc xác nhận metadata. Schema 22 trường và bảng Excel 23 cột được giữ nguyên.

## Kết hợp PDF + OCR (H1)

Chọn riêng **Kết hợp PDF + OCR (thử nghiệm)** cho PDF. Mặc định tài liệu mới vẫn dùng phương pháp cũ; ảnh PNG/JPG chỉ dùng OCR. H1 cần đủ model đã khóa giống chế độ OCR, không tải model tự động.

H1 chạy OCR B1024, sau đó chọn text có sẵn theo từng dòng khi đủ điều kiện về vị trí, Unicode, font, độ hiển thị và ảnh trang. Dòng không đủ điều kiện giữ nguyên kết quả OCR. PDF scan không có text đủ tin cậy sẽ giữ OCR. Ngưỡng H1 v1 giữ nguyên từ nghiên cứu, SHA256 cấu hình `227a2a272661b86077c47b230d7977e63e802fe276ecdc86336275ce2c5e672f`.

**So sánh** hiển thị H1 cạnh bản OCR gốc của cùng lượt chạy. JSON H1 có `ocr_result` chứa toàn bộ bản gốc; mỗi dòng có `ocr_text`, `text_source` và lý do fallback. Kết quả và bản nháp metadata của các phương pháp được giữ riêng. Mọi giá trị bóc tách từ H1 vẫn cần người đối chiếu. PDF có hình học không hỗ trợ hoặc thiếu bằng chứng độ hiển thị sẽ giữ OCR.

H1 chưa được chấp nhận làm phương pháp mặc định. Kiểm thử phần mềm không chứng minh độ chính xác OCR hoặc độ chính xác 22 trường. Không thay preprocessing, weights hoặc tự động sửa dấu; probe BILINEAR chưa được đưa vào app.

## Việc cần làm tiếp

1. Khóa bộ DEV mới gồm PDF scan và PDF có text; người gán nhãn đọc ảnh trước khi xem kết quả OCR. Kiểm tra không trùng dữ liệu train/val/blind hoặc bộ đã dùng chọn phương án.
2. Gán nhãn riêng số/ký hiệu, ngày, cơ quan, loại văn bản và trích yếu. So sánh kết quả OCR hiện hành với H1 trên cùng tài liệu; báo cáo riêng scan và PDF có text, lỗi ký tự và khớp chính xác từng trường.
3. Kiểm tra thao tác sửa/xác nhận và file Excel thực tế trên Windows và Mac. Các bản cài cũ chưa có thay đổi này; phải dùng artifact được build từ commit tích hợp hoặc mới hơn.
4. Chỉ cân nhắc bật H1 mặc định khi qua tiêu chí đã khóa và không gây lỗi mới ở trường quan trọng. Điều tra hồi quy BILINEAR riêng trước khi cân nhắc sửa ba ca dấu synthetic; không thay gate sau khi xem kết quả.

Không cần mở hay dùng tập blind đã niêm phong cho việc phát triển giao diện. PDF, nhãn, model và báo cáo OCR thật tiếp tục được giữ ngoài Git.

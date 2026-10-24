# Kiểm toán quyền phát hành miễn phí — đang BLOCKED

Đây là danh mục kiểm tra, không phải kết luận tư vấn pháp lý. **Không thu tiền vẫn là phân phối.**

| Thành phần | Đã biết | Cần xác minh trước khi public |
| --- | --- | --- |
| Code VietDoc | Repo chưa có root LICENSE | Quyền của chủ sở hữu, contributors, giấy phép mã nguồn mở/corresponding source |
| PyMuPDF | AGPLv3 hoặc thương mại: https://pymupdf.io/licensing | Tuân thủ AGPL cho ứng dụng và nguồn tương ứng hoặc được cấp giấy phép thương mại |
| PaddleOCR source | Vendored PaddleOCR/LICENSE là Apache-2.0 | Giữ notices/copyright, phiên bản và thay đổi |
| PP-OCRv6_medium_det | model_lock.json khóa SHA-256 detector | Model card, nguồn gốc, giấy phép **weights**, quyền phân phối |
| VietOCR upstream | https://github.com/pbcquoc/vietocr Apache-2.0 | Notices, chính xác fork/kiến trúc |
| VietOCR B1024 fine-tuned | Checkpoint/encoder/decoder đã khóa SHA-256 | Pretraining weights, nguồn dữ liệu/nhãn, consent, quyền phân phối trọng số sau fine-tune |
| Electron/Python/Paddle/runtime | Pinned packaging requirements | SBOM, third-party notices, native libraries, VC++ redistributable |
| Repo và dữ liệu | Repo còn private, có nhiều worktrees và nghiên cứu | Rà soát **toàn bộ history của mọi branch/tag**, tránh leak blind/GT/weights |

NO-GO đến khi có tài liệu phê duyệt từng hạng mục. Không tự gắn license cho code của người khác.

# Kiểm toán quyền phát hành miễn phí — đang BLOCKED

Đây là danh mục kiểm tra, không phải kết luận tư vấn pháp lý. **Không thu tiền vẫn là phân phối.**

| Thành phần | Đã biết | Cần xác minh trước khi public |
| --- | --- | --- |
| Code VietDoc | Repo chưa có root LICENSE | Quyền của chủ sở hữu, contributors, giấy phép mã nguồn mở/corresponding source |
| PyMuPDF | AGPLv3 hoặc thương mại: https://pymupdf.io/licensing | Tuân thủ AGPL cho ứng dụng và nguồn tương ứng hoặc được cấp giấy phép thương mại |
| PaddleOCR source | Vendored PaddleOCR/LICENSE là Apache-2.0 | Giữ notices/copyright, phiên bản và thay đổi |
| PP-OCRv6_medium_det | model_lock.json khóa SHA-256 detector | Model card, nguồn gốc, giấy phép **weights**, quyền phân phối |
| VietOCR upstream | https://github.com/pbcquoc/vietocr Apache-2.0 | Notices, chính xác fork/kiến trúc |
| VietOCR B1024 fine-tuned | Chủ dự án đã tự fine-tune trên GPU, **khởi tạo từ `vgg_transformer.pth` pretrained** (không phải train from scratch). Báo cáo local xác nhận `loaded=True`, **253/253 parameter tensors** khớp checkpoint khi bắt đầu; `desktop/model_lock.json` khóa hash output B1024. | Quyền phân phối **đúng file pretrained** và file weights/ONNX phát sinh; provenance của dữ liệu/nhãn, consent, attribution/NOTICE. Apache-2.0 ghi trong README upstream cho **thư viện** chưa tự chứng minh license của từng artifact trọng số. |
| Electron/Python/Paddle/runtime | Pinned packaging requirements | SBOM, third-party notices, native libraries, VC++ redistributable |
| Repo và dữ liệu | Repo còn private, có nhiều worktrees và nghiên cứu | Rà soát **toàn bộ history của mọi branch/tag**, tránh leak blind/GT/weights |

NO-GO đến khi có tài liệu phê duyệt từng hạng mục. Không tự gắn license cho code của người khác.

## Bằng chứng nguồn gốc checkpoint B1024 (ghi nhận 24/10/2026)

**Nguồn: kết quả PowerShell được chủ dự án gửi trong quá trình chuẩn bị release; không chứa trọng số model hay dữ liệu tài liệu.**

- `configs/vietnamese/vietocr/exp_b_width1024.yml`: `pretrain: models/vietocr/vgg_transformer.pth`.
- `models/vietocr/finetuned/exp_b_width1024/report.json` (chỉ xem tại máy chủ dự án): `pretrained.file = vgg_transformer.pth`, `pretrained.loaded = True`, `pretrained.parameter_tensors = 253`, `pretrained.identical_to_checkpoint = 253`.
- Trên nhánh `feat/vietnamese-recognizer-bakeoff`, `train_vietocr.py` đọc checkpoint qua `load_pretrained(...)` và dừng nếu tải không đầy đủ; `build_vietocr_config.py` chỉ định đường dẫn pretrained nói trên.
- `cnn.pretrained: false` chỉ không tải riêng ImageNet weights; **không xóa việc nạp checkpoint VietOCR**.
- Chủ dự án thực hiện GPU training; điều này không thay đổi nguồn khởi tạo. **Kết luận kỹ thuật:** fine-tuned from pretrained (không được ghi là trained entirely from scratch).
- Upstream: https://github.com/pbcquoc/vietocr — README ghi Apache 2.0 cho **thư viện**, và pretrained model được cung cấp; tài liệu đó chưa phải bằng chứng đầy đủ rằng `vgg_transformer.pth` mang quyền tái phân phối riêng hoặc rằng nguồn dữ liệu huấn luyện checkpoint gốc đã được xử lý phù hợp.

**Chưa đủ bằng chứng và vẫn BLOCKED cho public binary:** xác minh SHA-256/checkpoint gốc với nguồn phát hành chính thức, điều khoản cụ thể của artifact `vgg_transformer.pth`, quyền đối với dataset và fine-tuned B1024 weights/ONNX, cùng giấy phép PyMuPDF/ứng dụng. Không công khai các model, nhãn/dataset, local reports hay thay đổi GitHub visibility trong bước này.

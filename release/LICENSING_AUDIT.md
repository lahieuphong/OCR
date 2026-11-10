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

## Bổ sung 11/11/2026: hệ thống phát hành Windows (Setup và Portable)

**Vẫn BLOCKED cho phát hành công khai.** Các điểm dưới đây là dữ kiện kỹ thuật cho việc rà soát, không phải kết luận pháp lý.

- Mỗi bản build có `resources/licenses/THIRD_PARTY_NOTICES.txt`, `notices.json` và file giấy phép của từng thành phần, do `packaging/windows/collect_notices.py` tạo từ chính bản build (dist-info của các gói Python, gói npm có trong frontend, CPython, Electron, model). Danh sách "NEEDS REVIEW" là đầu vào để rà soát, không phải giấy phép.
- Bản build kiểm chứng ngày 11/11/2026 (sau review, gói npm lồng nhau được gộp) có 303 thành phần, 17 mục cần xem xét:
  - giấy phép chia sẻ mã nguồn: PyMuPDF (AGPL-3.0 hoặc thương mại), python-bidi (LGPL, giữ ở dạng file rời để có thể thay thế), certifi và tqdm (MPL-2.0), jszip (MIT hoặc GPL-3.0, có thể chọn MIT), FFmpeg trong Electron (`ffmpeg.dll`, LGPL-2.1+);
  - runtime Microsoft Visual C++ đi kèm các wheel, và D3DCompiler đi kèm Electron;
  - NSIS và các plug-in trong Setup (nsis7z theo LGPL-2.1);
  - hai bộ trọng số model;
  - giấy phép của chính VietDoc OCR, chưa được chọn;
  - vài gói npm khai báo MIT nhưng không có file giấy phép trong gói. Cần bổ sung văn bản giấy phép trước khi phân phối.
  - Bootloader PyInstaller (GPL-2.0+ kèm ngoại lệ bootloader) được liệt kê kèm giấy phép, không cần xem xét thêm.
- Hai phương án phát hành (mã nguồn mở hoặc proprietary), nghĩa vụ, chi phí và bằng chứng còn thiếu: [GIAY_PHEP_PHUONG_AN.md](GIAY_PHEP_PHUONG_AN.md).
- PP-OCRv6_medium_det: model card có trong thư mục model trên máy (bản Hugging Face `PaddlePaddle/PP-OCRv6_medium_det`) ghi `license: apache-2.0`. Model card được đóng kèm `resources/licenses/models/`. Thư mục model không có file LICENSE, nên cần xác nhận điều khoản cho đúng file `inference.pdiparams` đã khóa SHA-256.
- VietOCR B1024: bản build mang `encoder.onnx`, `decoder_step.onnx` và `weights.pth`.
  - `weights.pth` là checkpoint PyTorch 152 MB. Nó chỉ được đọc để kiểm SHA-256 khi khởi động (`contract.verify_frozen_onnx(require_weights=True)`); nhận dạng chỉ dùng ONNX.
  - Phát hành công khai `weights.pth` nghĩa là trao trọng số có thể huấn luyện tiếp trực tiếp.
  - Chủ dự án cần quyết định có giữ file này trong bản công khai hay không. Bỏ file đòi sửa hợp đồng model và test khóa `test_frozen_pins`; việc này chưa được làm.
- Bản nội bộ có tên file `-INTERNAL`, và trang giấy phép của bộ cài là `INTERNAL_NOTICE.txt`. Bản công khai (`--channel public`) bị script build từ chối cho đến khi có `desktop/build-resources/PUBLIC_LICENSE.txt` do chủ dự án duyệt.

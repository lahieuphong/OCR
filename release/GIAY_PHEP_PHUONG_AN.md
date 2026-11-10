# Hồ sơ giấy phép: hai phương án phát hành VietDoc OCR

Tài liệu cho chủ dự án ra quyết định. **Đây không phải tư vấn pháp lý.** Tài liệu không chọn giấy phép thay chủ dự án và không cấp quyền phân phối model. Rà soát ngày 11/11/2026, dựa trên bản build `0.1.0` nội bộ và danh sách `THIRD_PARTY_NOTICES.txt` do `packaging/windows/collect_notices.py` tạo.

## 1. Hiện trạng cần biết ngay

- **Repository `lahieuphong/OCR` đã public nhưng chưa có file LICENSE.** Người khác xem được mã nguồn nhưng chưa có quyền dùng, sửa hay phân phối lại.
- **Pre-release `v0.1.0-beta.1` đang công khai, kèm `VietDoc-OCR-0.1.0-Windows-x64-Setup.exe`.**
  - Đây là bản không có model, nhưng có PyMuPDF (AGPL-3.0), PaddlePaddle, Electron… và chưa có thông báo giấy phép đầy đủ.
  - Phân phối bản này mà ứng dụng chưa có giấy phép tương thích AGPL và chưa kèm thông báo là rủi ro tuân thủ.
  - Chủ dự án cần chọn một trong hai:
    - chuyển release này về Draft, hoặc gỡ tài sản tạm thời;
    - hoàn tất nghĩa vụ theo phương án A ngay.
- **Các nhánh nghiên cứu công khai chứa dữ liệu đánh giá.** `datasets/vietnamese_recognition/manifests/blind_test.tsv`, `blind_test/blind_test.tsv`, `benchmarks/vietnamese/ground_truth.tsv` và `label_quarantine.tsv` có mặt trên 9 nhánh `feat/*`.
  - Đây là văn bản chép từ tài liệu thật. Quét từ khóa không thấy dấu hiệu dữ liệu cá nhân (CCCD, ngày sinh, thửa đất), nhưng chủ dự án cần xác nhận quyền công bố các tài liệu nguồn.
  - Bộ blind test không còn "mù" nữa.
- **Không có model nào trong Git.** Model chỉ có trong các bản build nội bộ nằm ngoài repository.

## 2. Từng thành phần

| Thành phần | Giấy phép đã biết | Nghĩa vụ chính khi phân phối | Bằng chứng còn thiếu |
|---|---|---|---|
| Mã nguồn VietDoc OCR | Chưa chọn | Có LICENSE, xác nhận quyền tác giả | Giấy phép do chủ dự án chọn; xác nhận mọi người đóng góp đồng ý |
| PyMuPDF 1.28.2 (MuPDF) | AGPL-3.0 **hoặc** giấy phép thương mại của Artifex ([tài liệu PyMuPDF](https://pymupdf.readthedocs.io/en/latest/about.html)) | AGPL: toàn bộ ứng dụng phân phối theo điều khoản tương thích AGPL, kèm mã nguồn tương ứng. Thương mại: theo hợp đồng | Quyết định A/B; nếu B thì cần báo giá và hợp đồng Artifex (trang không công bố giá) |
| PaddlePaddle 3.2.0, PaddleX 3.7.2, PaddleOCR (vendored) | Apache-2.0 | Giữ LICENSE/NOTICE, ghi rõ thay đổi | Kiểm tra NOTICE của từng gói trong `resources/licenses` |
| VietOCR (thư viện) | Apache-2.0 ([README](https://github.com/pbcquoc/vietocr)) | Giữ giấy phép, ghi công | Không |
| Trọng số pretrained `vgg_transformer.pth` | **Không công bố.** README chỉ ghi "Pretrain model được cung cấp sẵn", không có điều khoản riêng cho trọng số hay bộ dữ liệu huấn luyện | Chưa xác định | Văn bản cho phép của tác giả VietOCR, hoặc điều khoản chính thức; SHA-256 của file gốc so với nguồn phát hành |
| Trọng số B1024 fine-tune (`encoder.onnx`, `decoder_step.onnx`, `weights.pth`) | Phái sinh từ pretrained và dữ liệu huấn luyện của dự án | Phụ thuộc quyền với pretrained và quyền với dữ liệu | Danh sách nguồn của từng tài liệu huấn luyện (24 PDF thật và dữ liệu tổng hợp) với quyền sử dụng; quyết định có phát hành `weights.pth` hay không (file này chỉ dùng để kiểm SHA-256; nhận dạng dùng ONNX) |
| PP-OCRv6_medium_det | Model card tải về cùng model ghi `license: apache-2.0` | Giữ thông báo Apache-2.0 | Bản lưu trang Hugging Face hoặc file LICENSE tại thời điểm tải; xác nhận đúng file đã khóa SHA-256 |
| python-bidi | LGPL-3.0 | Để người dùng thay được thư viện (đang để file rời); kèm văn bản LGPL | Không, nếu giữ dạng file rời |
| FFmpeg trong Electron (`ffmpeg.dll`) | LGPL-2.1+ | DLL riêng thay được; thông báo; đề nghị cung cấp mã nguồn | Đường dẫn tới mã nguồn đúng phiên bản Electron |
| certifi, tqdm | MPL-2.0 | Thông báo; mã nguồn của chính các file MPL nếu sửa (không sửa) | Không |
| jszip | MIT **hoặc** GPL-3.0 | Chọn nhánh MIT, giữ thông báo | Ghi rõ lựa chọn MIT |
| Microsoft Visual C++ runtime (trong wheel), D3DCompiler (trong Electron) | Điều khoản phân phối lại của Microsoft | Chỉ phân phối các file được phép | Xác nhận các DLL nằm trong danh sách redistributable |
| Electron/Chromium | MIT kèm thông báo Chromium | Kèm `LICENSE.electron.txt` và `LICENSES.chromium.html` (đã kèm) | Không |
| Bootloader PyInstaller | GPL-2.0+ kèm ngoại lệ bootloader | Kèm thông báo | Không |
| NSIS và plug-in (chỉ trong Setup) | zlib/libpng; nsis7z theo LGPL-2.1 | Thông báo cho trình cài đặt | Danh sách plug-in electron-builder nhúng |
| Gói npm thiếu file giấy phép | Khai báo MIT | Kèm văn bản MIT | Bổ sung văn bản giấy phép |

**Notices, SBOM, mã nguồn tương ứng.**
- `THIRD_PARTY_NOTICES.txt` và `notices.json` đã được sinh từ chính bản build.
- Còn thiếu: SBOM theo định dạng chuẩn (SPDX hoặc CycloneDX), và gói "mã nguồn tương ứng" cho từng release (mã ứng dụng đúng commit, script build, spec, lockfile, PaddleOCR vendored, chỉ dẫn lấy mã nguồn của MuPDF/FFmpeg đúng phiên bản).

## 3. Phương án A: phát hành mã nguồn mở

Ứng dụng phân phối theo một giấy phép tương thích AGPL-3.0 (ví dụ AGPL-3.0-or-later), mã nguồn công khai trên `lahieuphong/OCR`.

- **Nghĩa vụ:**
  - Thêm LICENSE ở thư mục gốc.
  - Mỗi bản phát hành chỉ rõ commit và tag, kèm hoặc trỏ tới mã nguồn tương ứng đủ để build lại.
  - Bộ cài hiển thị giấy phép (`desktop/build-resources/PUBLIC_LICENSE.txt`) và giữ mọi thông báo bên thứ ba.
  - Phần LGPL giữ dạng thay được.
  - Không thêm điều khoản hạn chế những quyền mà AGPL cho phép.
- **Chi phí:** không phí giấy phép. Phần việc gồm: chọn giấy phép, viết LICENSE và PUBLIC_LICENSE, đóng gói mã nguồn cho từng release, rà soát lịch sử công khai, thu thập bằng chứng về model.
- **Hệ quả:** người khác được sửa, phân phối lại, kể cả dùng thương mại, miễn tuân thủ AGPL.
- **Không giải quyết được:** quyền phân phối trọng số. Trọng số không trở thành hợp pháp nhờ chọn giấy phép mã nguồn. Nếu chưa có quyền với `vgg_transformer.pth` và dữ liệu huấn luyện, có thể phát hành **bản không kèm VietOCR B1024**, nhưng như vậy không còn OCR bản scan.
- **Bằng chứng còn thiếu:** quyết định giấy phép; điều khoản trọng số pretrained; nguồn và quyền của dữ liệu huấn luyện; bản lưu điều khoản PP-OCRv6; SBOM.

## 4. Phương án B: giữ ứng dụng proprietary

Mã nguồn vẫn có thể công khai để xem ("source-available"), nhưng không cấp quyền sử dụng hay phân phối lại. Bản phát hành đi kèm một EULA.

- **Nghĩa vụ:**
  - Dùng PyMuPDF theo **giấy phép thương mại của Artifex**, hoặc thay PyMuPDF bằng thư viện có giấy phép dễ dãi (ví dụ pypdfium2, Apache-2.0 hoặc BSD-3-Clause). Thay thư viện là thay đổi kỹ thuật, cần chạy lại toàn bộ hồi quy lớp chữ PDF, render và 22 trường.
  - Các phần LGPL, MPL, Apache và MIT còn lại vẫn phải kèm thông báo và giữ khả năng thay thế (LGPL).
- **Chi phí:**
  - Phí giấy phép Artifex (chỉ có khi liên hệ báo giá), hoặc công sức thay thư viện và chạy hồi quy.
  - Soạn EULA.
  - Nên có tư vấn pháp lý về việc repository public mà không có giấy phép mở.
- **Hệ quả:** giữ quyền kiểm soát ứng dụng. Repository public vẫn hiển thị mã nguồn, chỉ là không cấp quyền dùng.
- **Không giải quyết được:** quyền phân phối trọng số, giống phương án A.
- **Bằng chứng còn thiếu:** báo giá và hợp đồng Artifex, hoặc kế hoạch thay PyMuPDF; EULA; cùng nhóm bằng chứng về model như phương án A.

## 5. Chủ dự án cần quyết định

1. Phương án A hay B, và tên giấy phép (nếu là A).
2. Xử lý pre-release `v0.1.0-beta.1` đang công khai.
3. Xử lý các nhánh nghiên cứu công khai có dữ liệu đánh giá; có cần bộ blind test mới không.
4. Liên hệ tác giả VietOCR về điều khoản trọng số pretrained; xác nhận quyền với tài liệu huấn luyện.
5. Có phát hành `weights.pth` hay chỉ phát hành ONNX. Bỏ `weights.pth` cần sửa hợp đồng model và test khóa.
6. Ký số hay phát hành UNSIGNED kèm hướng dẫn kiểm tra SHA-256.

## 6. Danh sách bằng chứng (gắn vào `release/check_release_candidate.py`, nhóm `legal`)

- `project_license_and_source`: LICENSE, PUBLIC_LICENSE, gói mã nguồn tương ứng của đúng commit.
- `pymupdf_rights`: tuân thủ AGPL (phương án A), hoặc hợp đồng Artifex (phương án B).
- `vietocr_weights_rights`: điều khoản pretrained, nguồn và quyền của dữ liệu huấn luyện.
- `paddle_detector_rights`: điều khoản PP-OCRv6 đã lưu, SHA-256 khớp.
- `third_party_sbom_notices`: THIRD_PARTY_NOTICES đã duyệt, SBOM chuẩn.
- `windows_runtime_rights`: các DLL Microsoft thuộc danh sách được phân phối lại.

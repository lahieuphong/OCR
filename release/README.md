# VietDoc OCR — chuẩn bị bản miễn phí cho cộng đồng

**2026-10-24: NO-GO phát hành installer có model.** Đây là giai đoạn kiểm toán và QA, không phải phê duyệt pháp lý.

Đã có: mã nguồn Windows Electron/PyInstaller/NSIS trên main (PR #11), CI model-free 3/3 PASS và kết quả nội bộ NSIS installer 558,6 MB trên máy DEV. Chưa chứng minh OCR có model trên Windows 10/11 sạch, chưa xác minh quyền chia sẻ weights, chưa ký số, chưa hoàn thiện SBOM.

Repository GitHub hiện **private**, chưa có root LICENSE. Giấy phép PyMuPDF là AGPLv3 hoặc thương mại (https://pymupdf.io/licensing). Free-to-download vẫn phải tuân thủ giấy phép. PaddleOCR và VietOCR upstream Apache-2.0 không tự động cho phép công bố mọi fine-tuned weight hoặc bộ dữ liệu huấn luyện.

## Chính sách phiên bản

- Dự kiến v0.1.0-rc.1 cho community release candidate, sau khi duyệt. v0.1.0 chỉ khi đủ điều kiện chính thức.
- **Git tag không mang theo installer.** Cần GitHub Release gắn file VietDoc OCR Setup.exe, SHA256SUMS.txt, notices và corresponding source.
- Release/tag của repository private không thể cho cả cộng đồng tải về. Không đổi repo sang public trước khi quét toàn bộ Git history, mọi branch/tag và private research files. Có thể tạo kho public mới từ snapshot nguồn đã kiểm toán, miễn đáp ứng nghĩa vụ corresponding-source.
- Không commit/upload weights, dataset, checkpoint, installer nội bộ, private staging hay evidence vào Git, Git LFS hoặc CI artifact.

## Evidence gate

Script release/check_release_candidate.py kiểm tra SHA-256 của installer và đủ 22 bằng chứng có status PASS, report SHA-256, đặt **ngoài repository**. Schema là vietdoc-community-release-attestation-v1, với các field tag, source_commit, installer_sha256, gates. Mỗi gate = object chứa status, report (absolute path) và sha256. Xem hằng REQUIRED trong script.

Chạy PowerShell (thay các đường dẫn và SHA minh họa):

    py -3.12 release/check_release_candidate.py --attestation "E:\VietDoc_release_private\attestation.json" --installer "E:\VietDoc_release_private\VietDoc OCR Setup.exe" --source-sha "<40-character SHA>"

Script PASS chỉ là **đủ báo cáo và hash khớp**, không chứng minh bằng chứng được tạo từ máy thật hoặc xác nhận quyền pháp lý. Chủ dự án phải đọc và phê duyệt từng báo cáo. Xem QA_MATRIX.md, LICENSING_AUDIT.md.

Sau khi mọi gate đạt: trên GitHub chọn Releases → Draft a new release → Choose tag v0.1.0-rc.1 → upload file exe được duyệt và checksum → Save draft → chỉ Publish khi có phê duyệt cuối cùng.

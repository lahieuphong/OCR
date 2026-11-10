# VietDoc OCR — chuẩn bị bản miễn phí cho cộng đồng

**2026-10-24: NO-GO phát hành installer có model.** Đây là giai đoạn kiểm toán và QA, không phải phê duyệt pháp lý.

**2026-11-11:** đã có hệ thống build bản phát hành Windows gồm Setup và Portable có model (`packaging/windows/build_release.py`). Quy trình, cấu trúc GitHub Release, repository phát hành công khai và danh sách việc còn lại nằm trong [PHAT_HANH_WINDOWS.md](PHAT_HANH_WINDOWS.md). Phát hành công khai vẫn BLOCKED cho đến khi rà soát giấy phép xong.

Đã có: mã nguồn Windows Electron/PyInstaller/NSIS trên main (PR #11), CI model-free 3/3 PASS và kết quả nội bộ NSIS installer 558,6 MB trên máy DEV. Chưa chứng minh OCR có model trên Windows 10/11 sạch, chưa xác minh quyền chia sẻ weights, chưa ký số, chưa hoàn thiện SBOM.

Repository GitHub `lahieuphong/OCR` đã được chủ dự án chuyển sang **public** (11/11/2026) nhưng vẫn chưa có root LICENSE: mã nguồn công khai để xem, chưa cấp quyền sử dụng hay phân phối lại. Giấy phép PyMuPDF là AGPLv3 hoặc thương mại (https://pymupdf.io/licensing). Free-to-download vẫn phải tuân thủ giấy phép. PaddleOCR và VietOCR upstream Apache-2.0 không tự động cho phép công bố mọi fine-tuned weight hoặc bộ dữ liệu huấn luyện.

## Chính sách phiên bản

- Dự kiến v0.1.0-rc.1 cho community release candidate, sau khi duyệt. v0.1.0 chỉ khi đủ điều kiện chính thức.
- **Git tag không mang theo installer.** Cần GitHub Release gắn `VietDoc-OCR-v<ver>-Windows-x64-Setup.exe`, `VietDoc-OCR-v<ver>-Windows-x64-Portable.zip`, `SHA256SUMS.txt`, `BUILD_INFO.txt`, notices và corresponding source.
- Repository đã public từ 11/11/2026: toàn bộ lịch sử Git, mọi nhánh, tag và GitHub Release hiện có (kể cả pre-release `v0.1.0-beta.1`) đều công khai. Kết quả rà soát lịch sử và việc cần chủ dự án quyết định nằm trong [PHAT_HANH_WINDOWS.md](PHAT_HANH_WINDOWS.md) và [GIAY_PHEP_PHUONG_AN.md](GIAY_PHEP_PHUONG_AN.md).
- Không commit/upload weights, dataset, checkpoint, installer nội bộ, private staging hay evidence vào Git, Git LFS hoặc CI artifact.

## Evidence gate

Script release/check_release_candidate.py kiểm tra SHA-256 của Setup và Portable (tên file theo tag, ví dụ `VietDoc-OCR-v0.1.0-rc.1-Windows-x64-Setup.exe` và `…-Portable.zip`) và đủ 23 bằng chứng có status PASS, report SHA-256, đặt **ngoài repository**. Schema là vietdoc-community-release-attestation-v1, với các field tag, source_commit, installer_sha256, portable_sha256, gates. Mỗi gate = object chứa status, report (absolute path) và sha256. Xem hằng REQUIRED trong script.

Chạy PowerShell (thay các đường dẫn và SHA minh họa):

    py -3.12 release/check_release_candidate.py --attestation "<evidence>\attestation.json" --installer "<release>\VietDoc-OCR-v0.1.0-rc.1-Windows-x64-Setup.exe" --portable "<release>\VietDoc-OCR-v0.1.0-rc.1-Windows-x64-Portable.zip" --source-sha "<40-character SHA>"

Script PASS chỉ là **đủ báo cáo và hash khớp**, không chứng minh bằng chứng được tạo từ máy thật hoặc xác nhận quyền pháp lý. Chủ dự án phải đọc và phê duyệt từng báo cáo. Xem QA_MATRIX.md, LICENSING_AUDIT.md.

Sau khi mọi gate đạt: trên GitHub chọn Releases → Draft a new release → Choose tag v0.1.0-rc.1 → upload Setup, Portable, SHA256SUMS.txt, BUILD_INFO.txt, notices và mã nguồn tương ứng đã duyệt → Save draft → chỉ Publish khi có phê duyệt cuối cùng.

# Phát hành VietDoc OCR cho Windows qua GitHub Releases

Tài liệu cho người phát hành. Hướng dẫn cho người dùng cuối nằm ở [windows/HUONG_DAN_CAI_DAT.md](windows/HUONG_DAN_CAI_DAT.md).

**Trạng thái (11/11/2026):** chủ dự án quyết định phát hành công khai `v0.1.0` khi rà soát giấy phép ([GIAY_PHEP_PHUONG_AN.md](GIAY_PHEP_PHUONG_AN.md)) và kiểm thử Windows 10 vẫn còn mở. Các việc ở mục 9 vẫn phải hoàn tất.

## 1. Hai bản tải về

| | Setup | Portable |
|---|---|---|
| File | `VietDoc-OCR-v<ver>-Windows-x64-Setup.exe` | `VietDoc-OCR-v<ver>-Windows-x64-Portable.zip` |
| Dạng | NSIS, cài cho người dùng hiện tại, không cần quyền quản trị | ZIP của đúng thư mục ứng dụng đã kiểm tra |
| Lối tắt | Start Menu; Desktop tùy chọn | Không |
| Dữ liệu ứng dụng | `%APPDATA%\VietDoc OCR`, giữ khi nâng cấp hoặc gỡ | `VietDoc OCR Data` cạnh ứng dụng |
| Gỡ bỏ | Settings → Apps | Xóa thư mục |

**Vì sao Portable là ZIP, không phải một file EXE.** Target `portable` của electron-builder là một EXE tự giải nén. Mỗi lần mở, nó giải nén toàn bộ ứng dụng (1,31 GB, 2.137 file ở bản build ngày 11/11/2026) vào `%TEMP%`. Như vậy việc khởi động chậm, mỗi lần chạy ghi hàng GB ra ổ đĩa, và ứng dụng chạy từ thư mục tạm nên thư mục `VietDoc OCR Data` cạnh ứng dụng không còn tác dụng. ZIP chạy trực tiếp từ nơi giải nén và giữ dữ liệu cạnh ứng dụng.

Bản nội bộ có thêm `-INTERNAL` trong tên file và tên gỡ cài đặt, và trang giấy phép của bộ cài là `desktop/build-resources/INTERNAL_NOTICE.txt`. Bản công khai giữ đúng tên ở bảng trên.

## 2. Build

Build trên máy Windows có model, theo [packaging/README.md](../packaging/README.md) mục 1 và mục 8:

```
<venv-packaging>\Scripts\python.exe packaging\windows\build_release.py --out <thư mục build mới, ngoài checkout>
    --model-root <thư mục models đã xác minh> --paddlex-home <thư mục PaddleX có PP-OCRv6_medium_det>
    --vietocr-license <vietocr>\LICENSE [--channel public]
```

Script dừng ở bất kỳ bước kiểm tra nào không đạt. Nó không upload, không gắn tag và không cài đặt gì. Kết quả:

- `release/`: Setup, Portable, `SHA256SUMS.txt`, `BUILD_INFO.txt` (phiên bản, commit, model, trạng thái ký số), hướng dẫn, ghi chú phát hành, `THIRD_PARTY_NOTICES.txt`;
- `reports/`: `build_report.json`, bản quét gói, log từng bước;
- `work/`: bản build trung gian, kể cả biến thể smoke dùng cho QA. Thư mục này không bao giờ được phát hành.

`--channel public` bị từ chối khi cây Git còn thay đổi chưa commit, hoặc khi chưa có `desktop/build-resources/PUBLIC_LICENSE.txt` (văn bản giấy phép do chủ dự án duyệt).

## 3. Kiểm tra trước khi phát hành

1. Unit test, build và hồi quy OCR như mọi thay đổi (backend, frontend, desktop, packaging).
2. `packaging/windows/check_packaged_ocr.py`: chạy OCR thật bằng backend của bản đã cài và bản Portable đã giải nén, so với backend chạy từ mã nguồn.
3. Smoke giao diện bằng biến thể smoke của cùng bản build: OCR, Bóc tách nhanh, xuất JSON 22 trường và Excel.
4. Cài, mở lại, nâng cấp, gỡ; Portable ở đường dẫn tiếng Việt có khoảng trắng; không còn tiến trình sau khi thoát; không có kết nối ra ngoài.
5. Windows 10 và Windows 11 sạch, offline: quy trình và script trong [windows/QA_MAY_SACH.md](windows/QA_MAY_SACH.md).
6. Cổng bằng chứng [check_release_candidate.py](check_release_candidate.py): đủ báo cáo PASS và SHA-256 khớp với file sẽ phát hành.

## 4. Cấu trúc một GitHub Release

Tag `v<ver>` trỏ đúng commit đã build. Tiêu đề: `VietDoc OCR v<ver> cho Windows`. Nội dung lấy từ `windows/RELEASE_NOTES_v<ver>.md`, đã điền ngày, commit, kích thước và kết quả kiểm thử. Các tài sản đính kèm:

| Tài sản | Nguồn |
|---|---|
| `VietDoc-OCR-v<ver>-Windows-x64-Setup.exe` | `release/` của bản build đã kiểm định |
| `VietDoc-OCR-v<ver>-Windows-x64-Portable.zip` | như trên |
| `SHA256SUMS.txt`, `BUILD_INFO.txt` | như trên |
| `HUONG_DAN_CAI_DAT.md`, `THIRD_PARTY_NOTICES.txt` | như trên |
| Mã nguồn tương ứng (nếu giấy phép yêu cầu) | `git archive` của đúng commit, đã kiểm toán |

Luôn tạo **Draft** trước, đối chiếu SHA-256 của tài sản đã upload với `SHA256SUMS.txt`, và chỉ bấm Publish khi chủ dự án duyệt. Tag mới không tự sinh release: không workflow nào được tự động publish.

## 5. Kênh phát hành công khai `VietDoc-OCR-Releases`

Từ 11/11/2026, repository phát triển `lahieuphong/OCR` đã **public**, toàn bộ lịch sử và nhánh của nó cũng vậy. Vì vậy:
- mã nguồn tương ứng có thể trỏ thẳng tới tag của `OCR`;
- không còn lý do giữ lịch sử ở chế độ private;
- nhưng các nhánh nghiên cứu đang công khai dữ liệu đánh giá, chủ dự án cần quyết định cách xử lý ([GIAY_PHEP_PHUONG_AN.md](GIAY_PHEP_PHUONG_AN.md), mục 1).

Đề xuất vẫn tạo repository riêng **`VietDoc-OCR-Releases`** cho người dùng cuối (chưa tạo trong phiên này). Lý do: trang tải gọn, không lẫn nhánh nghiên cứu và CI, và có thể đổi chính sách mã nguồn sau này mà không ảnh hưởng kênh tải.

- **Nội dung:**
  - README tiếng Việt: giới thiệu, yêu cầu Windows, nút tải, kiểm tra SHA-256, giới hạn;
  - giấy phép và `THIRD_PARTY_NOTICES.txt`;
  - `HUONG_DAN_CAI_DAT.md`;
  - GitHub Releases mang các tài sản ở mục 4.
- **Mã nguồn tương ứng:** mỗi release ghi commit và tag của `lahieuphong/OCR`, và kèm `VietDoc-OCR-v<ver>-source.zip` (`git archive` của đúng commit, đã quét, đủ để build lại).
  - Release cũng kèm hướng dẫn lấy mã nguồn MuPDF/FFmpeg đúng phiên bản nếu giấy phép yêu cầu.
  - Chỉ đăng EXE và ZIP là không đủ.
- **Không bao giờ có:** trọng số tách rời ngoài bộ cài, dữ liệu huấn luyện, Ground Truth, báo cáo nội bộ, khóa hay token. Không sao chép lịch sử Git sang.
- **Quyền và an toàn:**
  - chỉ chủ dự án có quyền ghi, bật xác thực hai lớp, bảo vệ tag `v*`;
  - không có workflow tự publish;
  - tài sản chỉ upload từ `release/` của bản build đã qua cổng bằng chứng.
- **Các bước khi giấy phép xong:**
  1. Tạo repository trống, chỉ có README và LICENSE.
  2. Build `--channel public` từ commit sạch đã gắn tag trên `OCR`.
  3. Chạy cổng bằng chứng.
  4. Tạo Draft Release, upload tài sản và mã nguồn.
  5. So SHA-256 sau khi upload.
  6. Chủ dự án bấm Publish.

**Xung đột với bản INTERNAL cũ.** Bộ cài nội bộ cũ (`electron-builder.installer.yml`, "VietDoc OCR (INTERNAL)") cũng tên "VietDoc OCR", nên dùng chung thư mục cài mặc định, lối tắt và `%APPDATA%\VietDoc OCR`. Trước khi cài bản phát hành, gỡ bản INTERNAL đó. Một `desktop.config.json` cũ trong `%APPDATA%\VietDoc OCR` có `modelRoot` sẽ được ưu tiên hơn model đi kèm. `Chay_VietDoc.cmd` (chạy từ mã nguồn) cũng dùng `%APPDATA%\VietDoc OCR`: không chạy nó cùng lúc với bản cài, vì cửa sổ mở sau sẽ chỉ chuyển sang cửa sổ đang mở.

## 6. Tự động hóa bằng GitHub Actions

Hiện có: `vietdoc-packaging-ci.yml` (Windows, không model) chạy unit test, build backend và Electron, kiểm tra fuses, quét gói, probe backend, smoke không model, cổng smoke của bản release, và khi chạy tay thì tạo bộ cài test không model. `vietdoc-community-release-gate.yml` kiểm tra script cổng bằng chứng.

Quy trình đề xuất cho bản phát hành:

1. Unit test và hồi quy (CI, không model).
2. Build frontend và backend (CI).
3. Đóng gói Setup và Portable **có model**: chỉ trên máy build của chủ dự án (`build_release.py`), vì model không được đưa lên Actions.
4. Quét gói tìm dữ liệu nhạy cảm (`scan_bundle.py --allow-locked-models`), tự động trong script.
5. Kiểm tra thành phần và giấy phép (`collect_notices.py`), tự động trong script; chủ dự án duyệt danh sách "NEEDS REVIEW".
6. SHA-256 (`SHA256SUMS.txt`), tự động trong script.
7. Kiểm thử bản đã đóng gói (mục 3), trên máy build và Windows sạch.
8. Tạo Draft Release và upload tài sản đã duyệt: làm tay, hoặc sau này bằng một workflow `workflow_dispatch` chỉ tạo **Draft**.

Chưa thêm workflow tạo release vì hai lý do: bản đầy đủ cần model, không được phép đưa lên CI; phát hành công khai còn BLOCKED. Repository đã public nên runner chuẩn của GitHub Actions chạy được trở lại cho các job không model. Một bản build trên CI luôn là **bản test không model** và phải được ghi rõ như vậy, không được giới thiệu là VietDoc OCR đầy đủ.

## 7. Cập nhật tự động: lộ trình

Theo quyết định của chủ dự án (11/11/2026), bản Setup **tự cập nhật** như các ứng dụng Electron thông thường. Mã ở `desktop/electron/lib/updater.js`, dùng `electron-updater`, nguồn là GitHub Releases của `lahieuphong/OCR`:

- Chỉ bản Setup đã cài mới cập nhật: có trình gỡ cài đặt cạnh exe và có `app-update.yml`. Không cập nhật khi chạy Portable, chạy từ mã nguồn, chạy smoke test hay các bản test/nội bộ.
- Kiểm tra một lần khoảng 10 giây sau khi mở, tải ở nền, cài khi đóng ứng dụng. Có thể kiểm tra tay qua menu **VietDoc → Kiểm tra cập nhật…**. Mọi sự kiện được ghi vào `main.log`.
- File tải về được kiểm SHA-512 theo `latest.yml`. Cập nhật vi sai dùng blockmap và bản sao installer trong `%LOCALAPPDATA%\vietdoc-ocr-desktop-updater`.
- **Rủi ro còn lại:** bản build chưa ký số, nên không kiểm được chữ ký nhà phát hành. Ai chiếm được quyền ghi Release của repository có thể đẩy bản cập nhật cho mọi máy đã cài. Cần bật xác thực hai lớp, bảo vệ tag, và ký số sớm (khi đó đặt `publisherName`).
- Phát hành: `packaging/windows/build_release.py --channel public`, rồi `packaging/windows/publish_github_release.py --publish`.

## 8. Ký số

Bản build hiện **UNSIGNED**: `BUILD_INFO.txt` ghi rõ trạng thái này, và hướng dẫn chỉ cho phép "More info → Run anyway" sau khi SHA-256 khớp, không bao giờ tắt SmartScreen hay Defender. Các lựa chọn cần chủ dự án tìm hiểu điều kiện hiện hành: chứng chỉ ký mã OV hoặc EV từ một CA, chứng chỉ ký mã cho nhà phát triển mã nguồn mở, dịch vụ ký mã đám mây, hoặc chương trình ký miễn phí cho dự án mã nguồn mở (thường yêu cầu repository công khai và giấy phép OSI). Khi có chứng chỉ, ký `VietDoc OCR.exe`, `vietdoc-backend.exe` và Setup trước khi tính SHA-256.

## 9. Việc phải xong trước khi phát hành công khai

1. Giấy phép của VietDoc OCR, và cách tuân thủ PyMuPDF: AGPL kèm mã nguồn tương ứng, hoặc giấy phép thương mại.
2. Quyền phân phối trọng số: VietOCR B1024 fine-tuned từ `vgg_transformer.pth` (quyền đối với checkpoint gốc, dữ liệu huấn luyện, file ONNX và `weights.pth`), và PP-OCRv6_medium_det (model card ghi apache-2.0, cần xác nhận cho đúng file).
3. Duyệt `THIRD_PARTY_NOTICES.txt`, nhất là các mục "NEEDS REVIEW": LGPL, MPL, AGPL và runtime Microsoft Visual C++.
4. `desktop/build-resources/PUBLIC_LICENSE.txt`, văn bản giấy phép mà bộ cài hiển thị.
5. Kiểm thử trên Windows 10 và Windows 11 sạch, offline, tài khoản có tên tiếng Việt.
6. Ký số, hoặc quyết định rõ ràng phát hành UNSIGNED kèm hướng dẫn kiểm tra SHA-256.
7. Repository phát hành công khai, ảnh chụp mã nguồn đã kiểm toán, cổng bằng chứng PASS.

## 10. Bản Release Candidate đầu tiên

Đề xuất `v0.1.0-rc.1`. Phiên bản trong `desktop/package.json` đổi thành `0.1.0-rc.1` bằng một commit trên `main`. Bản này được build bằng `--channel public` từ đúng commit đó khi mục 9 xong, và phát hành dạng **pre-release** trên repository công khai. Trước đó, các bản build nội bộ giữ tên `-INTERNAL` và chỉ dùng trên máy được phép.

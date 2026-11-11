# Danh sách nhiều tài liệu và xuất Excel

Chọn/kéo thả nhiều PDF trong panel đầu vào; **Thêm tài liệu** giữ các kết quả
hiện có. **Đổi tệp** chỉ thay thế tài liệu đang chọn. Tên trùng nhau được phân
biệt bằng STT và UUID trong phiên. Xóa/đổi/chạy lại tài liệu có chỉnh sửa cần
xác nhận; thêm tài liệu không làm mất bản nháp khác.

Mọi tài liệu được xử lý bằng **Bóc tách nhanh** (`metadata_fast`, header trang
1); giao diện không có lựa chọn phương pháp khác. **Bóc tách tất cả** chờ từng
`/api/ocr` hoàn tất trước khi gửi tài liệu tiếp theo, kể cả khi một tài liệu
lỗi. **Thử lại** trong bảng chỉ xử lý tài liệu lỗi đó. Giới hạn và khóa xử lý
của backend được giữ nguyên.

Tab **Danh sách văn bản** mở form tương ứng khi nhấn mã/tên tài liệu. Raw result,
bản nháp, lỗi và xác nhận nằm trong bộ nhớ theo UUID của tài liệu; chuyển
tài liệu/tab không trộn hoặc mất chỉnh sửa. Xác nhận toàn tài liệu không điền
trường thiếu. Sửa metadata sẽ hủy trạng thái xác nhận đó. Không ghi tài liệu vào
localStorage, telemetry hay dịch vụ ngoài.

**Xuất danh sách Excel** dùng các checkbox của bảng và kết quả bóc tách nhanh
của từng tài liệu. Nút bị khóa khi chưa có kết quả hợp lệ hoặc đang xử lý.
Tài liệu chưa xử lý, lỗi hoặc có giá trị sai schema/ngày không hợp lệ bị loại.
Xuất thiếu tài liệu, bản nháp còn thiếu/cần kiểm tra hoặc mã chế độ sử dụng
chưa phân loại đều cần xác nhận rõ; giá trị chưa xác định vẫn rỗng. STT được
đánh lại liên tục theo thứ tự danh sách. Excel xuất giá trị đã chỉnh sửa;
TXT/JSON OCR gốc vẫn xuất nguyên response của backend.

## Workbook

Tên mặc định `Danh_sach_van_ban.xlsx`. Sheet `Danh sách văn bản` có duy nhất
một hàng header và một hàng cho mỗi tài liệu, đúng 23 cột theo thứ tự:

| Cột | Tiêu đề | Key |
|---|---|---|
| A | STT | STT |
| B | Mã tài liệu | docId |
| C | Mã văn bản | arcDocCode |
| D | Thời hạn lưu trữ | maintenance |
| E | Loại tài liệu | typeName |
| F | Số tài liệu | codeNumber |
| G | Ký hiệu văn bản | codeNotation |
| H | Ngày ban hành | issuedDate |
| I | Cơ quan ban hành | organName |
| J | Trích yếu nội dung | subject |
| K | Ngôn ngữ | language |
| L | Số trang | numberOfPage |
| M | Ký hiệu thông tin | inforSign |
| N | Từ khóa | keyword |
| O | Chế độ sử dụng | mode |
| P | Mức độ tin cậy | confidenceLevel |
| Q | Bút tích | autograph |
| R | Tình trạng vật lý | format |
| S | Quy trình xử lý | process |
| T | Chế độ dự phòng | riskRecovery |
| U | Tình trạng dự phòng | riskRecoveryStatus |
| V | Ghi chú | description |
| W | Màu con dấu | isCan |

STT là số nguyên; toàn bộ 22 giá trị nghiệp vụ là chuỗi, theo schema hiện có
trong [METADATA.md](METADATA.md). `docId` luôn rỗng. Mã có số 0 đầu và ngày
`DD-MM-YYYY` giữ nguyên dưới dạng text. Giá trị chỉ được gán bằng primitive
string; không tạo formula, hyperlink hoặc external link, kể cả khi bắt đầu
bằng `=`, `+`, `-`, `@` hay tab. Không thêm dấu nháy vào dữ liệu. Ký tự điều
khiển XML không hợp lệ hoặc ô vượt 32.767 ký tự sẽ báo lỗi, không âm thầm cắt.

Mọi ô trong vùng bảng, kể cả ô rỗng, dùng Times New Roman 13. Header đậm,
xanh nhạt; thân trắng, viền xám mảnh, wrap, STT căn giữa và nội dung căn trái.
Độ rộng giới hạn 7–64; hàng được ước tính theo nội dung, giới hạn 26–120 pt
(header 48 pt). Nội dung dài vẫn lưu đủ và có thể tăng chiều cao hàng trong
Excel. Freeze tại B2, AutoFilter toàn vùng, không merge. Sheet phụ `Nguồn tài
liệu` có STT, basename, phương pháp và trạng thái; không chứa đường dẫn, token,
model hash hoặc raw response. Các thuộc tính workbook chỉ ghi tên ứng dụng.

## Thư viện và bảo mật

ExcelJS 4.4.0, MIT, [upstream](https://github.com/exceljs/exceljs). Giấy phép
được phân phối tại `public/licenses/exceljs.txt`. Vite đóng gói browser writer
offline; chỉ import khi xuất, dùng blob download từ app origin hiện có. Không
cần Office, COM, Python hoặc mạng để xuất. Không thay đổi quyền Electron,
sandbox, token/Host/Origin, pipeline hay quy tắc trích xuất metadata.

Build kiểm tra ngày 25-10-2026: JS chính 399,49 kB (gzip 126,55 kB), chunk
ExcelJS tải khi xuất 940,19 kB (gzip 271,33 kB). Vite vẫn báo cảnh báo kích
thước chunk; không tắt cảnh báo. Không tải thư viện/CDN ngoài lúc chạy.

`npm audit` cả lockfile và production trả 0 cảnh báo trong lần kiểm tra này.
Scoped override `exceljs > uuid = 11.1.1` vá dependency Node theo
[GHSA-w5hq-g745-h8pq](https://github.com/advisories/GHSA-w5hq-g745-h8pq).
Override không rebuild browser bundle đóng sẵn của upstream. App chỉ ghi
workbook từ chuỗi đã kiểm tra, không đọc XLSX đầu vào, không dùng conditional
formatting hoặc các API UUID v3/v5/v6 với buffer bị ảnh hưởng. Audit lockfile
không phải bằng chứng mọi đoạn mã trong bundle upstream đều đã được vá.

## Kiểm thử

- `npm ci`, `npm test`, `npm run build`, `npm audit`.
- `excelExport.test.js`: ghi XLSX vào thư mục tạm thật, mở lại bằng ExcelJS,
  kiểm tra 23 cột, thứ tự, dữ liệu, mọi style/ô rỗng, freeze/filter, Unicode,
  mã/ngày, chuỗi dài, formula injection và whitelist dữ liệu xuất.
- `documentBatch.test.js`, `Batch.test.jsx` và regression `App.test.jsx`:
  hàng đợi tuần tự, lỗi giữa, thử lại, thêm/xóa/drop, tên trùng, mode riêng,
  giữ chỉnh sửa, xác nhận, loại dòng không hợp lệ, raw TXT/JSON không đổi.
- Electron smoke thực sự chọn ba PDF, gửi ba request tuần tự, chỉnh tài liệu
  đầu, chuyển qua các tài liệu, so raw text, tải XLSX qua UI và ghi 22 giá trị
  form vào `batch_expected.json` ngoài repository. `--smoke-batch-dir` tùy chọn
  dùng ba PDF tổng hợp `officialLetter.pdf`, `decision.pdf`, `resolution.pdf`;
  nếu không có, smoke dùng ba bản sao của PDF DEV được cung cấp.
- `desktop/scripts/check_excel_export.py`: đọc ZIP/XML bằng Python stdlib
  độc lập ExcelJS, kiểm tra từng giá trị UI và style của cả hai sheet. CI
  Electron Windows/Linux chạy bước này trên file tải xuống thực tế.
  Smoke không thay đổi release gate.

QA Windows ngày 25-10-2026: Electron không model và có model thật đều đạt
(OCR thật trên PDF tổng hợp được phép, B1024, hai trang/tám dòng). Batch ba
PDF tổng hợp có mã khác nhau chạy native text, tối đa một request cùng lúc.
XLSX tải xuống đã được mở thêm bằng Microsoft Excel 12.0 ở chế độ chỉ đọc:
3 dòng, 23 cột, mọi giá trị khớp UI, font/size đúng, không formula,
AutoFilter A1:W4 và freeze hàng/cột đúng. COM chỉ dùng cho QA ngoài ứng dụng.
LibreOffice native **NOT VERIFIED**; đã kiểm tra cấu trúc OOXML và Excel thực.
Tất cả PDF/XLSX, ảnh, log và báo cáo riêng nằm ngoài Git.

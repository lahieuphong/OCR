# VietDoc OCR

Ứng dụng OCR tiếng Việt chạy local trên Windows bằng Electron, PaddleOCR detector và VietOCR B1024 ONNX. Giao diện hỗ trợ PDF/PNG/JPG, chọn native text hoặc OCR, metadata 22 trường và xuất nhiều tài liệu ra XLSX 23 cột.

**Nguồn ứng dụng hiện hành nằm trên nhánh main.** Thư mục mang tên demo/local_pdf_ocr vẫn là frontend/backend mà Electron và bản đóng gói sử dụng.

## Code đang được sử dụng

| Thư mục | Vai trò |
|---|---|
| [demo/local_pdf_ocr](demo/local_pdf_ocr/README.md) | FastAPI OCR backend và React/Vite frontend, metadata, hàng đợi và Excel. |
| [desktop](desktop/README.md) | Electron, bảo mật loopback/token, quản lý backend và smoke tests. |
| [packaging](packaging/README.md) | PyInstaller/NSIS, kiểm tra bundle và công cụ QA bản đóng gói. |
| [release](release/README.md) | Hồ sơ quyền phân phối và verifier kiểm 22 bằng chứng phát hành. |
| PaddleOCR | Dependency nguồn vendored; được dùng khi cài Python dependency và đóng gói. |

Model, dataset, tài liệu riêng tư, file build và node_modules nằm ngoài Git hoặc được ignore. Các nhánh training/parity/H1 là nghiên cứu riêng; chúng chưa được duyệt để thay pipeline trên main.

## Làm việc và chạy ứng dụng

Dùng `git worktree list` để tìm worktree của main. Không switch/reset một worktree nghiên cứu đang có thay đổi local.

Làm theo [desktop/README.md](desktop/README.md) để cài dependency và cấu hình Python/model/cache đã có. Nếu dùng các tài nguyên ở thư mục khác, cấu hình `VIETDOC_PYTHON`, `VIETDOC_MODEL_ROOT` và `VIETDOC_PADDLEX_HOME` theo tài liệu desktop/packaging. Không tải hoặc thay weights để vượt kiểm SHA.

Khi đã cấu hình đủ dependency/model, chạy từ root của main:

~~~powershell
npm --prefix demo/local_pdf_ocr/frontend run build
npm --prefix desktop start
~~~

## Kiểm tra trước khi thay đổi

~~~powershell
npm --prefix demo/local_pdf_ocr/frontend test
npm --prefix desktop test
python .github/scripts/run_backend_tests.py
~~~

Python cần môi trường có dependency phù hợp. Các test và CI model-free không chứng nhận độ chính xác OCR thật. Văn bản nhận dạng cần review; giá trị sửa trong metadata không được làm thay đổi raw OCR.

## Nhánh và phát hành

Xem [kiểm kê nhánh và quy tắc dọn Git](docs/BRANCHES.md). Giữ các PR nghiên cứu chưa merge theo quyết định của chủ dự án; chỉ dọn nhánh trùng/đã tích hợp có bằng chứng.

**Phát hành cộng đồng vẫn NO-GO** cho đến khi các gate quyền phân phối, privacy, clean-VM và signing trong [release](release/README.md) được đóng. Repository hiện chưa cấp giấy phép phân phối mới qua README này.

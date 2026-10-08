# Baseline PP-OCRv6 tiếng Việt

Chạy pipeline PP-OCRv6 nguyên bản của PaddleOCR trên tài liệu tiếng Việt và lưu
lại **output thô**, để các phase sau đo được chính xác model sai ở đâu.

Phase này không train, không fine-tune, không hậu xử lý, và không sửa bất kỳ
file nào trong `PaddleOCR/` (thư mục đó là snapshot của upstream).

## Cấu hình baseline

| Thành phần | Giá trị |
| --- | --- |
| API | `PaddleOCR(lang="vi", ocr_version="PP-OCRv6", ...).predict_iter(...)` |
| Text detection | `PP-OCRv6_medium_det` |
| Text recognition | `PP-OCRv6_medium_rec` |
| Document orientation | `PP-LCNet_x1_0_doc_ori` (bật mặc định) |
| Document unwarping | `UVDoc` (bật mặc định) |
| Textline orientation | `PP-LCNet_x1_0_textline_ori` (bật mặc định) |
| PaddleOCR | snapshot upstream `dab3fe3537`, import từ `PaddleOCR/` |

`lang="vi"` cùng `ocr_version="PP-OCRv6"` được PaddleOCR resolve thành cặp model
trên (xem `PaddleOCR/paddleocr/_pipelines/ocr.py`, hàm `_get_ocr_model_names`).
Script không truyền tên model trực tiếp, vì khi có tên model tường minh thì
PaddleOCR bỏ qua `lang` và `ocr_version`. Thay vào đó `run_ocr.py` đọc lại config
pipeline đã resolve và dừng ngay nếu hai model không đúng như bảng.

## Cài đặt

Chạy từ thư mục gốc của repository.

```bash
# 1. Môi trường ảo ở gốc repo (không tạo bên trong PaddleOCR/)
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel

# 2. PaddlePaddle bản CPU, đúng phiên bản tài liệu local chỉ định
python -m pip install paddlepaddle==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/

# 3. PaddleOCR từ source local, ở chế độ editable
SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PADDLEOCR="3.8.0.dev13+gdab3fe353" \
  python -m pip install -e ./PaddleOCR
```

Ghi chú:

- Trên máy Apple Silicon phải dùng Python bản arm64 (ví dụ Homebrew). Python
  x86_64 chạy qua Rosetta sẽ kéo về wheel sai kiến trúc.
- Máy có GPU NVIDIA thì thay bước 2 bằng gói `paddlepaddle-gpu` tương ứng với
  phiên bản driver, theo `PaddleOCR/docs/version3.x/paddlepaddle_installation.en.md`.
  Baseline này mới chỉ được kiểm chứng trên CPU.

### Vì sao cần `SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PADDLEOCR`

`PaddleOCR/pyproject.toml` lấy version động qua `setuptools_scm`, tức là chạy
`git describe` trong thư mục source. `PaddleOCR/` ở đây là snapshot không kèm
lịch sử git của upstream, nên bước cài đặt dừng với lỗi:

```text
LookupError: setuptools-scm was unable to detect version for .../PaddleOCR.
```

Biến môi trường ở trên là cơ chế chính thức của `setuptools_scm` cho trường hợp
này. Cách làm này không sửa file nào trong `PaddleOCR/`.

Giá trị `3.8.0.dev13+gdab3fe353` không phải số tự đặt. Đó là kết quả của
`python -m setuptools_scm` (bản 10.3.4) chạy trên một bản checkout sạch của
upstream tại commit `dab3fe3537`, nhánh `main`:

- `git describe --tags --long --match "v[0-9]*"` trả về `v3.7.0-13-gdab3fe3537`;
- scheme `release-branch-semver` trên nhánh không phải release tăng minor, cho
  ra `3.8.0.dev13`.

Có thể kiểm chứng lại bằng cách clone `PaddlePaddle/PaddleOCR`, checkout
`dab3fe3537` và chạy hai lệnh trên.

Bước cài editable sinh ra `PaddleOCR/paddleocr.egg-info/` và các thư mục
`__pycache__/`. Chúng đã được `PaddleOCR/.gitignore` bỏ qua, nên
`git diff -- PaddleOCR` vẫn rỗng.

### Phiên bản đã resolve khi thiết lập baseline

| Gói | Phiên bản |
| --- | --- |
| Python | 3.12.11 (arm64) |
| paddlepaddle | 3.2.0 (CPU) |
| paddlex | 3.7.2 |
| paddleocr | 3.8.0.dev13+gdab3fe353 (editable, `./PaddleOCR`) |
| numpy | 2.3.5 |
| opencv-contrib-python | 4.10.0.84 |
| pypdfium2 | 5.14.0 |

`paddlepaddle` được ghim cứng. Các gói còn lại do pip resolve trong khoảng mà
`PaddleOCR/pyproject.toml` cho phép (`paddlex[ocr-core]>=3.7.0,<3.8.0`).

## Kiểm tra môi trường

```bash
python experiments/vietnamese_baseline/inspect_environment.py
```

Script in ra JSON gồm hệ điều hành, Python, PaddlePaddle, thiết bị, GPU NVIDIA
(nếu có), vị trí import của `paddleocr`, và trạng thái git của repo. Trường
`paddleocr.is_local_source` phải là `true`. Máy không có GPU vẫn chạy bình
thường, các trường liên quan nhận giá trị `null`, `0` hoặc danh sách rỗng.

## Chạy OCR

```bash
python experiments/vietnamese_baseline/run_ocr.py \
  --input experiments/vietnamese_baseline/input \
  --output experiments/vietnamese_baseline/output \
  --device cpu
```

| Tham số | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `--input` | bắt buộc | Một file, hoặc một thư mục (không quét đệ quy) |
| `--output` | `experiments/vietnamese_baseline/output` | Thư mục chứa kết quả |
| `--device` | `cpu` | `cpu` hoặc `gpu:0` |
| `--profile` | không có | Nhãn tuỳ chọn cho cấu hình, được ghi vào `metadata.json` |
| `--use-doc-orientation [BOOL]` | `true` | `use_doc_orientation_classify` của PaddleOCR |
| `--use-doc-unwarping [BOOL]` | `true` | `use_doc_unwarping` của PaddleOCR |
| `--use-textline-orientation [BOOL]` | `true` | `use_textline_orientation` của PaddleOCR |

Tắt một bước bằng cách truyền `false`, ví dụ `--use-doc-unwarping false`.

Định dạng nhận vào: `.pdf`, `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`. PDF được
PaddleOCR xử lý trực tiếp (render bằng `pypdfium2`, đã có sẵn trong dependency),
không cần renderer riêng. Với thư mục, file được xử lý theo thứ tự tên file tăng
dần; file ẩn bị bỏ qua.

Script gọi `predict_iter()`, dạng trả kết quả từng trang của `predict()` trong
API 3.x (`predict()` chính là `list(predict_iter())`). Kết quả giống hệt nhau,
nhưng mỗi lúc chỉ giữ một trang trong RAM và đo được thời gian của từng trang.

Để so sánh nhiều cấu hình trên cùng một tập tài liệu, dùng
`benchmarks/vietnamese/run_benchmark.py`; script đó gọi lại `run_ocr.py` và ghi
mỗi profile vào `output/<profile>/`.

Nếu yêu cầu `--device gpu:0` mà PaddlePaddle không thấy thiết bị CUDA, script
dừng với thông báo lỗi. PaddleX trong trường hợp đó sẽ tự chuyển sang CPU mà
không báo, làm `metadata.json` ghi sai thiết bị.

Lần chạy đầu tiên sẽ tải model về `~/.paddlex/official_models/`.

## Output

Mỗi tài liệu có một thư mục riêng, đặt theo tên file không kèm đuôi. Nếu hai
file trùng tên (ví dụ `a.pdf` và `a.png`) thì dùng cả đuôi: `a_pdf`, `a_png`.

```text
output/<document-name>/
├── raw/
│   ├── page_0001.json    # kết quả gốc của trang, ghi bằng save_to_json() của PaddleOCR
│   └── page_0001.png     # ảnh mà OCR thực sự chạy trên đó
├── visualization/
│   ├── page_0001_ocr_res_img.png
│   └── page_0001_preprocessed_img.png   # chỉ có khi bật tiền xử lý tài liệu
├── result.json           # gộp kết quả gốc của mọi trang
├── lines.jsonl           # mỗi dòng văn bản một bản ghi
├── text.txt              # văn bản thô
└── metadata.json         # cấu hình và môi trường của lần chạy
```

`lines.jsonl` — mỗi dòng là một object:

```json
{"document": "...", "page": 1, "line_index": 0, "text": "...", "confidence": 0.99, "box": [[x, y], [x, y], [x, y], [x, y]]}
```

| Trường | Nguồn trong kết quả PaddleOCR 3.x |
| --- | --- |
| `document` | tên thư mục output của tài liệu |
| `page` | `page_index + 1` với PDF; `1` với ảnh đơn (`page_index` là `null`) |
| `line_index` | vị trí trong `rec_texts` của trang, bắt đầu từ 0, giữ nguyên thứ tự pipeline trả về |
| `text` | `rec_texts[i]`, không chỉnh sửa |
| `confidence` | `rec_scores[i]` (float) |
| `box` | `rec_polys[i]`, đa giác 4 điểm, toạ độ nguyên |

Hình chữ nhật bao (`rec_boxes`) và các trường còn lại nằm trong `result.json`
và `raw/`.

`text.txt` chứa mỗi dòng nhận dạng trên một dòng, các trang cách nhau bằng ký tự
form feed (`\f`).

`metadata.json` được ghi sau cùng, nên sự có mặt của nó cho biết tài liệu đã
chạy xong trọn vẹn. Ngoài cấu hình và môi trường, nó ghi số dòng và thời gian
inference của từng trang trong trường `pages`.

### Hệ toạ độ của `box`

Toạ độ tính theo ảnh trong `raw/page_XXXX.png`, **không phải** theo file gốc:

- trang PDF được render ở zoom 2.0 trước khi OCR;
- khi bật xoay hoặc unwarping, ảnh đã bị biến đổi hình học so với bản gốc.

Khi cắt ảnh dòng cho việc gán nhãn hay train, hãy cắt từ `raw/page_XXXX.png`.

## Nguyên tắc: giữ nguyên output thô

Script không sửa chính tả, không dùng từ điển, không dùng language model hay
LLM, không dùng regex hay heuristic để sửa dấu, và không chuẩn hoá Unicode. Nếu
model trả về `chuấn` hay `triến` thì output ghi đúng như vậy.

Danh sách `benchmarks/vietnamese/hard_cases.txt` chỉ dùng để theo dõi regression,
không bao giờ dùng để sửa output.

## Giới hạn đã biết

- Unwarping (`UVDoc`) làm thay đổi hình học của trang và có thể làm đổi cả nội
  dung nhận dạng. Trên ảnh mẫu của upstream, bật unwarping cho 9 dòng, tắt cho
  10 dòng. Với bản scan phẳng hoặc PDF sinh từ máy, nên chạy cả hai chế độ để so
  sánh trước khi chốt cấu hình.
- Tốc độ tham khảo trên Apple M2, 8 GB RAM, CPU: khoảng 18 giây mỗi trang PDF
  khi bật đủ ba bước tiền xử lý, RAM đỉnh khoảng 2,5 GB.

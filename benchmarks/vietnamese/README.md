# Benchmark tiếng Việt

Đo chất lượng OCR tiếng Việt của baseline PP-OCRv6 và so sánh các cấu hình.
Mọi script ở đây chỉ **đọc và phân tích** output; không script nào sửa text mà
OCR trả về.

## Profile

| | A | B |
| --- | --- | --- |
| Tên | `ppocrv6_vi_unwarp_on` | `ppocrv6_vi_unwarp_off` |
| `use_doc_unwarping` | `true` | `false` |
| `use_doc_orientation_classify` | `true` | `true` |
| `use_textline_orientation` | `true` | `true` |
| Model | `PP-OCRv6_medium_det` + `PP-OCRv6_medium_rec`, `lang="vi"` | giống A |

Hai profile chỉ khác nhau ở unwarping. Ngưỡng và tham số detection giống nhau;
`compare_profiles.py` kiểm tra điều này trên config đã resolve và dừng nếu có
khác biệt nào khác.

## Quy trình

Chạy từ gốc repository, sau khi `source .venv/bin/activate`.

```bash
# 1. OCR từng profile, lần lượt (không chạy song song)
python benchmarks/vietnamese/run_benchmark.py \
  --input experiments/vietnamese_baseline/input --profile ppocrv6_vi_unwarp_on
python benchmarks/vietnamese/run_benchmark.py \
  --input experiments/vietnamese_baseline/input --profile ppocrv6_vi_unwarp_off

# 2. So sánh hai output với nhau
python benchmarks/vietnamese/compare_profiles.py

# 3. Tạo bản nháp để người kiểm tra sửa thành ground truth
python benchmarks/vietnamese/prepare_ground_truth.py candidates \
  --profile ppocrv6_vi_unwarp_off

# 4. (người làm) sửa candidate, rồi verify từng trang - xem ground_truth/README.md

# 5. Đo CER/WER và phân tích hard case trên các trang đã verified
python benchmarks/vietnamese/evaluate.py
python benchmarks/vietnamese/analyze_hard_cases.py
```

Khi chưa có trang nào được verified, bước 5 không tính gì và in
`CER/WER: PENDING HUMAN-VERIFIED GROUND TRUTH`.

## Các file

| File | Vai trò |
| --- | --- |
| `common.py` | Đường dẫn, định nghĩa profile, hàm đọc output và ground truth |
| `run_benchmark.py` | Chạy một profile bằng `experiments/vietnamese_baseline/run_ocr.py` |
| `compare_profiles.py` | So sánh A và B theo từng trang |
| `prepare_ground_truth.py` | Tạo candidate; ghi nhận trang đã được người kiểm tra |
| `evaluate.py` | CER/WER và danh sách lỗi |
| `analyze_hard_cases.py` | Thống kê đúng/sai cho từng mục trong `hard_cases.txt` |
| `hard_cases.txt` | Từ và cụm từ hay bị sai dấu, chỉ để theo dõi regression |
| `ground_truth/` | Văn bản đúng do người kiểm tra, xem `ground_truth/README.md` |
| `annotation_candidates/` | Bản nháp từ OCR, `verified: false` |
| `results/` | Kết quả sinh ra bởi các script |
| `ground_truth.tsv` | Khung cho ground truth mức dòng (dùng khi chuẩn bị dữ liệu train), hiện chỉ có header |
| `audit_charset.py` | Liệt kê chữ tiếng Việt mà từ điển PP-OCRv6 không có |
| `build_extended_dict.py` | Sinh `configs/vietnamese/ppocrv6_vi_ext_dict.txt` (dict gốc + các chữ thiếu) |
| `recognizer_bakeoff/` | So sánh PP-OCRv6 và VietOCR trên cùng line crop, xem `recognizer_bakeoff/README.md` |
| `tests/` | `python -m unittest discover -s benchmarks/vietnamese/tests` |

Output OCR của từng profile nằm ở
`experiments/vietnamese_baseline/output/<profile>/<document>/`.

## Kết quả trong `results/`

| File | Nội dung | Cần ground truth |
| --- | --- | --- |
| `profile_comparison.csv` | Số dòng, confidence trung bình, thời gian, text có giống nhau không, theo từng trang | không |
| `metrics.csv` | CER/WER theo từng trang và profile | có |
| `metrics_summary.csv` | Micro CER/WER toàn bộ tập, theo profile | có |
| `errors.jsonl` | Mỗi lỗi mức từ một bản ghi, kèm loại lỗi và ngữ cảnh | có |
| `hard_cases.csv` | Số lần đúng/sai của từng hard case | có |

Confidence cao hơn không có nghĩa là chính xác hơn. Chỉ CER/WER trên ground
truth đã verified mới nói lên độ chính xác.

## Cách tính

Mọi tỉ lệ đều là `khoảng cách Levenshtein / độ dài ground truth`.

| Chỉ số | Đơn vị | Chuẩn hoá trước khi so |
| --- | --- | --- |
| `cer_raw` | ký tự | không |
| `cer_nfc` | ký tự | chỉ Unicode NFC, cả hai phía |
| `wer_raw` | từ, tách theo khoảng trắng | không |
| `wer_nfc` | từ, tách theo khoảng trắng | chỉ Unicode NFC, cả hai phía |

Không lowercase, không bỏ dấu, không xử lý dấu câu. Văn bản của một trang là các
dòng nối bằng ký tự xuống dòng; ký tự xuống dòng được tính như một ký tự trong
CER.

Số liệu toàn tập là **micro**: tổng số lỗi chia cho tổng độ dài ground truth,
nên trang dài có trọng số lớn hơn trang ngắn.

## Loại lỗi trong `errors.jsonl`

Lỗi được tìm bằng cách gióng hàng từ của ground truth với từ của prediction
(sau NFC). Một loại chỉ được gán khi xác định được chắc chắn:

| `error_type` | Điều kiện |
| --- | --- |
| `accent` | Hai từ giống hệt nhau sau khi bỏ hết dấu (thanh, mũ, móc, trăng) |
| `missing_character` | Prediction thu được từ ground truth chỉ bằng cách bỏ ký tự, hoặc cả từ bị thiếu |
| `extra_character` | Ground truth thu được từ prediction chỉ bằng cách bỏ ký tự, hoặc có từ thừa |
| `substitution` | Hai từ cùng độ dài, khác nhau ở chữ cái |
| `segmentation` | Các từ giống hệt nhau khi bỏ khoảng trắng (dính từ hoặc tách từ) |
| `unknown` | Mọi trường hợp còn lại |

## Giới hạn đã biết: từ điển của PP-OCRv6 thiếu chữ tiếng Việt

Model `PP-OCRv6_medium_rec` chỉ xuất được các ký tự có trong từ điển của nó,
`PaddleOCR/ppocr/utils/dict/ppocrv6_dict.txt` (18.708 ký tự, trùng khớp với từ
điển trong file `inference.yml` của model đã tải). Đối chiếu 134 chữ cái có dấu
của tiếng Việt (67 chữ thường, 67 chữ hoa, dạng NFC) với từ điển đó:

- có trong từ điển: 46 chữ;
- **không có: 88 chữ**. Chữ thường bị thiếu:
  `ả ạ ằ ắ ẳ ẵ ặ ầ ấ ẩ ẫ ậ ẻ ẽ ẹ ề ế ể ễ ệ ỉ ị ỏ ọ ố ổ ỗ ộ ờ ớ ở ỡ ợ ủ ụ ừ ứ ử ữ ự ỳ ỷ ỹ ỵ`
- từ điển cũng không chứa dấu tổ hợp (combining mark), nên không thể ghép các
  chữ này từ chữ gốc và dấu.

Hệ quả: model không thể xuất ra 88 chữ này trong bất kỳ cấu hình nào. Output
của cả hai profile không chứa chữ nào trong số đó, và có những chuỗi bị khuyết
chữ như `thc hin`, `t chc`, `vưng mc`. Cả 13 mục trong `hard_cases.txt` đều chứa
ít nhất một chữ bị thiếu, và không mục nào xuất hiện trong output.
Vì vậy lựa chọn giữa profile A và B không giải quyết được nguồn lỗi chính; muốn
nhận dạng đúng các chữ này thì phải mở rộng từ điển khi fine-tune.

Danh sách đầy đủ kèm code point và tên Unicode: `python
benchmarks/vietnamese/audit_charset.py`. Hai chữ thuộc khối Latin Extended
Additional mà từ điển có là `Ạ` (U+1EA0) và `ồ` (U+1ED3); dạng còn lại của
chúng, `ạ` và `Ồ`, thì thiếu. Từ điển mở rộng và những gì cần làm để dùng được
nó: `configs/vietnamese/README.md`.

## Nguyên tắc

- `hard_cases.txt` chỉ dùng để đếm đúng/sai, không bao giờ dùng để sửa output.
- Ground truth phải do người kiểm tra; không lấy output OCR làm chuẩn.
- Không chọn cấu hình dựa trên confidence.

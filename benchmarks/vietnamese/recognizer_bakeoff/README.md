# Recognizer bake-off: PP-OCRv6 và VietOCR

So sánh hai model **nhận dạng** trên cùng một tập line crop và cùng một ground
truth: `PP-OCRv6_medium_rec` (nguyên bản) và VietOCR. Phần detection chỉ chạy
một lần, bằng PaddleOCR, và được dùng chung.

Mục đích là quyết định hướng đi cho tiếng Việt: fine-tune VietOCR, hay mở rộng
từ điển của PP-OCRv6 rồi fine-tune. Không có gì được train ở đây.

## Vì sao so sánh như thế này là công bằng

- **Cùng input.** Mỗi dòng detect được cắt thành một file PNG duy nhất trong
  `crops/`. Cả hai recognizer đọc đúng các file đó và kiểm tra SHA-256 ghi trong
  `manifest.jsonl` trước khi đọc. VietOCR không có detector riêng.
- **Cùng ground truth.** Mỗi dòng có một ground truth do người gõ. Vì hai model
  nhận cùng một crop nên khác biệt về cách tách dòng không ảnh hưởng tới CER.
- **Cùng tập dòng.** `evaluate_recognizers.py` dừng với `FAIL` nếu hai file
  prediction không phủ đúng cùng một tập id.
- **Mỗi model chạy ở cấu hình gốc của nó**, từng crop một (batch 1), trên CPU.

## Profile detection được đóng băng

| | |
| --- | --- |
| Profile | B, `ppocrv6_vi_unwarp_off` |
| `use_doc_orientation_classify` | `true` |
| `use_doc_unwarping` | `false` |
| `use_textline_orientation` | `true` |
| Detector | `PP-OCRv6_medium_det` |
| Tham số detection | giữ nguyên: `thresh 0.3`, `box_thresh 0.6`, `unclip_ratio 1.5`, `limit_side_len 64` (`min`) |

Đóng băng profile B chỉ để hai recognizer nhận cùng input. Đây không phải kết
luận rằng B tốt hơn A.

## Môi trường

Hai môi trường tách biệt, vì PaddleOCR dùng PaddlePaddle còn VietOCR dùng
PyTorch:

| Môi trường | Dùng cho |
| --- | --- |
| `.venv` | mọi script, trừ `run_vietocr.py` |
| `.venv-vietocr` | `run_vietocr.py` |

Tạo môi trường VietOCR (một lần):

```bash
git submodule update --init third_party/vietocr
/opt/homebrew/bin/python3.12 -m venv .venv-vietocr
.venv-vietocr/bin/pip install -r benchmarks/vietnamese/recognizer_bakeoff/requirements-vietocr.txt
mkdir -p models/vietocr
curl -L -o models/vietocr/vgg_transformer.pth https://vocr.vn/data/vietocr/vgg_transformer.pth
```

VietOCR không được cài bằng `pip`: code được import thẳng từ submodule đã pin,
nên chỉ cần các thư viện phục vụ inference.

## VietOCR được dùng

| | |
| --- | --- |
| Repository | `https://github.com/pbcquoc/vietocr`, submodule tại `third_party/vietocr` |
| Commit | `fe8c3a7fc714aec57ab81cec844eb3adf0c1636c` (2025-01-19, `v0.36-26-gfe8c3a7`) |
| Config | `vgg_transformer` = `config/base.yml` + `config/vgg-transformer.yml` của commit trên |
| Kiến trúc | backbone `vgg19_bn`, `seq_modeling: transformer`, greedy decoding (`beamsearch: False`) |
| Weights | `https://vocr.vn/data/vietocr/vgg_transformer.pth` (151.815.373 byte) |
| SHA-256 weights | `380512193a8b6cbf6fad80deacdc9b6939d10d473d199892fc6408d13775ea59` |
| Nơi lưu weights | `models/vietocr/` (ngoài git) |

**Vì sao `vgg_transformer`.** README của VietOCR cung cấp hai model pretrained,
train trên 10 triệu ảnh gồm cả văn bản scan: `vgg_transformer` (độ chính xác cả
chuỗi 0,8800) và `vgg_seq2seq` (0,8701, nhanh hơn khoảng 7 lần). README ghi
transformer "chính xác hơn", dù cũng nói chênh lệch giữa hai model không lớn;
notebook hướng dẫn của repo dùng `vgg_transformer`. Ở phase này độ chính xác
quan trọng hơn tốc độ.

**Ba chỗ khác với cấu hình tải về mặc định**, không chỗ nào đổi phép tính của
model:

- `weights`: bản tải sẵn của đúng file mà config trỏ tới, được kiểm tra
  SHA-256. `run_vietocr.py` dừng nếu file khác checksum trên.
- `device`: `cpu`, vì máy không có CUDA.
- `cnn.pretrained = False`, như notebook của VietOCR: trọng số ImageNet mà nó
  sẽ tải về đằng nào cũng bị checkpoint ghi đè.

Config được đọc từ file trong submodule thay vì tải từ `vocr.vn` lúc chạy. Tại
thời điểm viết, hai bản giống hệt nhau.

**Confidence.** `confidence` trong `vietocr.jsonl` là giá trị
`Predictor.predict(return_prob=True)` trả về: trung bình xác suất softmax của
các ký tự được decode. Nó không được hiệu chỉnh và không so được với score của
PP-OCRv6. Nếu VietOCR không trả về giá trị hữu hạn thì ghi `null`.

## Quy trình

Chạy từ gốc repository.

```bash
source .venv/bin/activate
B=benchmarks/vietnamese/recognizer_bakeoff

# 1. Cắt dòng, một lần duy nhất, từ output của profile B
python $B/export_line_crops.py
python $B/verify_crops.py            # crop có đúng là input của pipeline không

# 2. Nhận dạng cùng tập crop bằng hai model
python $B/run_ppocr_rec.py
.venv-vietocr/bin/python $B/run_vietocr.py      # môi trường PyTorch riêng

# 3. Chọn khoảng 150 dòng để người gõ ground truth
python $B/select_annotation_subset.py

# 4. (người làm) gõ ground truth
python $B/annotate.py --annotator "<tên>"

# 5. Tính chỉ số trên các dòng đã verified
python $B/evaluate_recognizers.py
```

Bước 1 đọc lại kết quả detection đã lưu ở
`experiments/vietnamese_baseline/output/ppocrv6_vi_unwarp_off/`; không chạy lại
model nào. Nếu chưa có output đó thì chạy `run_benchmark.py` cho profile B
trước.

## Các file

| File | Vai trò |
| --- | --- |
| `bakeoff_common.py` | Đường dẫn, profile đóng băng, đọc/ghi manifest, prediction, bảng annotation |
| `export_line_crops.py` | Cắt mỗi dòng detect thành một crop, ghi `manifest.jsonl` |
| `verify_crops.py` | Kiểm tra crop đúng là ảnh mà pipeline đã đưa cho recognizer |
| `run_ppocr_rec.py` | `PP-OCRv6_medium_rec` trên các crop → `predictions/ppocrv6.jsonl` |
| `run_vietocr.py` | VietOCR trên các crop → `predictions/vietocr.jsonl` |
| `select_annotation_subset.py` | Lấy mẫu phân tầng, tạo `annotation/manifest.tsv` |
| `annotate.py` | Công cụ gõ ground truth |
| `evaluate_recognizers.py` | Chỉ số, bảng ký tự thiếu, quy tắc quyết định |
| `inspect_rec_checkpoint.py` | Khảo sát checkpoint training của PP-OCRv6 |
| `PP_OCRV6_HEAD_ANALYSIS.md` | Kết quả khảo sát: mở rộng head cho 88 chữ |
| `requirements-vietocr.txt` | Phiên bản thư viện của `.venv-vietocr` |
| `manifest.jsonl`, `export_metadata.json` | Danh sách crop và nguồn gốc của chúng |
| `annotation/` | `manifest.tsv` (ground truth), `selection.json`, `annotation_log.jsonl`, `candidates/` |
| `results/` | Kết quả sinh ra bởi các script |

**Trong git và ngoài git.** Git chỉ chứa code, tài liệu và kết quả khảo sát head
(tên và shape tensor). Những thứ sau **không** vào git:

- ảnh: `crops/` và `annotation/candidates/`;
- `predictions/`, vì sinh lại được;
- file chứa text của tài liệu thật: `manifest.jsonl` (có `paddle_prediction`),
  `export_metadata.json`, mọi thứ trong `annotation/` (bảng annotation, ground
  truth, log), và các file trong `results/` có trích dẫn dòng văn bản.

Ground truth trong `annotation/manifest.tsv` là công sức của người gõ và không
sinh lại được, nhưng hiện chỉ nằm trên máy này. Nên sao lưu nó; nếu muốn đưa nó
vào một repository private thì xoá các dòng tương ứng trong `.gitignore`.

## Crop

Mỗi crop được tạo bằng chính toán tử mà pipeline PP-OCRv6 dùng giữa detection và
recognition (`CropByPolys` của PaddleX): lấy hình chữ nhật có diện tích nhỏ nhất
bao polygon, rồi biến đổi phối cảnh về hình chữ nhật thẳng. Dòng nghiêng được
nắn thẳng chứ không bị cắt theo bounding box. Dòng mà model orientation đánh dấu
là lộn ngược được xoay 180°, như pipeline vẫn làm.

`verify_crops.py` kiểm chứng điều này: đưa các file crop qua recognizer theo
đúng cách pipeline gom batch thì text và score **trùng với output của pipeline ở
364/364 dòng**.

`run_ppocr_rec.py` nhận dạng từng crop một, nên 29/364 prediction của nó khác
output của pipeline: trong pipeline, các crop cùng batch được pad về cùng chiều
rộng. Chạy từng crop một làm cho kết quả của một dòng không phụ thuộc vào các
dòng khác, và đặt hai recognizer vào cùng điều kiện.

Schema của `manifest.jsonl`:

```json
{
  "id": "21-bct.signed_p0001_l0001",
  "document": "21-bct.signed",
  "page": 1,
  "line_index": 1,
  "crop_path": "crops/21-bct.signed_p0001_l0001.png",
  "polygon": [[347, 9], [659, 7], [659, 28], [347, 30]],
  "paddle_prediction": "...",
  "paddle_confidence": 0.9659,
  "textline_orientation_angle": 0,
  "crop_width": 312,
  "crop_height": 20,
  "crop_sha256": "..."
}
```

`page` và `line_index` đếm từ 1. `line_index` ở đây bằng `line_index` trong
`lines.jsonl` của baseline cộng 1. `paddle_prediction` là output của pipeline
đầy đủ ở Phase 2, giữ lại để đối chiếu; chỉ số của bake-off dùng
`predictions/ppocrv6.jsonl`.

## Tập annotation

`select_annotation_subset.py` chọn 150 trong 364 dòng, với seed cố định. Các
tầng được lấp theo thứ tự dưới đây, trải đều qua tài liệu và trang; tầng cuối
là lấy ngẫu nhiên đều từ phần còn lại, để tập mẫu không chỉ gồm các trường hợp
được chọn có chủ đích.

| Tầng | Số dòng | Điều kiện |
| --- | --- | --- |
| `header` | 20 | Ít nhất 70% chữ cái là chữ hoa |
| `small_text` | 12 | Crop thấp, thuộc 10% thấp nhất |
| `digits_symbols` | 20 | Ít nhất 4 chữ số hoặc ký hiệu |
| `long_line` | 20 | Từ 60 ký tự |
| `complex_diacritics` | 20 | Ít nhất 3 chữ mang hai dấu (`ệ`, `ở`, `ấ`) |
| `missing_chars` | 24 | Prediction có chữ thuộc nhóm 88 chữ thiếu |
| `body` | 10 | Không phải header, không phải chữ nhỏ |
| `random` | 24 | Ngẫu nhiên từ phần còn lại |

Vì chưa có ground truth, các tầng được tính từ hai prediction và kích thước
crop. Chúng chỉ để định hướng việc lấy mẫu; `annotation/selection.json` ghi lại
lý do mỗi dòng được chọn.

Kết quả hiện tại: 48 dòng từ `21-bct`, 62 từ `216-tb`, 40 từ `738-ttg`; đủ cả
9 trang.

Schema của `annotation/manifest.tsv` (TSV thuần, không có quy tắc quote):

```text
id	document	page	crop_path	ppocr_prediction	vietocr_prediction	ground_truth	verified
```

Ban đầu `ground_truth` rỗng và `verified=false` ở mọi dòng. Không có prediction
nào được copy vào `ground_truth`. Script chọn mẫu không bao giờ ghi đè một bảng
đã có ground truth.

## Gõ ground truth

```bash
python benchmarks/vietnamese/recognizer_bakeoff/annotate.py --annotator "<tên>"
```

Với mỗi dòng chưa verified, công cụ in đường dẫn crop và hai prediction, rồi
chờ gõ. Crop hiện tại được chép sang `annotation/candidates/_current.png`: mở
file này trong VS Code (hoặc trình xem ảnh tự nạp lại khi file đổi) và nó sẽ
đổi theo từng dòng.

| Gõ | Tác dụng |
| --- | --- |
| nội dung của dòng | ground truth; sau đó `y` để lưu là verified, `r` để gõ lại, `s` để bỏ qua |
| `:s` | bỏ qua dòng này, không verified |
| `:e` | crop không có chữ (ground truth rỗng) |
| `:q` | lưu và thoát |

Nguyên tắc:

- Công cụ không tự điền gì: không chọn một trong hai prediction, không sửa chính
  tả, không gợi ý. Nhấn Enter khi chưa gõ gì không được tính là câu trả lời.
- Gõ **đúng những gì có trong ảnh**, kể cả lỗi chính tả của văn bản gốc. Hai
  prediction chỉ để tham khảo, cả hai đều có thể sai.
- Dòng không đọc được chắc chắn (chữ ký tay, dấu đóng chồng lên chữ) thì bỏ qua
  bằng `:s`. Một ground truth đoán mò làm sai lệch cả hai model.
- Ground truth được lưu ở Unicode NFC, bỏ khoảng trắng ở hai đầu. Nguyên văn
  phím gõ được giữ trong `annotation/annotation_log.jsonl`.
- Bảng được lưu sau mỗi lần xác nhận. Thoát giữa chừng rồi chạy lại sẽ tiếp tục
  từ dòng chưa làm. `--id <id>` để làm lại một dòng, `--redo` để duyệt lại tất
  cả.

Có thể gõ sẵn vào cột `ground_truth` của file TSV bằng editor; khi chạy
`annotate.py`, dòng đó hiện ra dưới dạng bản nháp và vẫn cần xác nhận từng dòng
mới thành `verified=true`.

## Chỉ số

`evaluate_recognizers.py` chỉ dùng các dòng `verified=true`. Khi chưa có dòng
nào, nó in `CER/WER: PENDING HUMAN-VERIFIED GROUND TRUTH` và không ghi file kết
quả.

| Chỉ số | Cách tính |
| --- | --- |
| CER raw / NFC | khoảng cách Levenshtein mức ký tự chia độ dài ground truth; NFC: chuẩn hoá cả hai phía trước |
| WER raw / NFC | như trên, theo từ tách bằng khoảng trắng |
| Exact line | tỉ lệ dòng nhận dạng đúng hoàn toàn |
| Missing-character accuracy | trong các lần xuất hiện của 88 chữ thiếu ở ground truth, tỉ lệ được nhận dạng đúng |
| Other-character accuracy | như trên, cho mọi ký tự còn lại |
| Hard-case accuracy | trong các lần xuất hiện của mục thuộc `../hard_cases.txt`, tỉ lệ đúng hoàn toàn |

Số liệu toàn tập là **micro**: tổng lỗi chia tổng độ dài ground truth. Không
lowercase, không bỏ dấu, không xử lý dấu câu; hàm tính dùng lại của
`../evaluate.py`.

Một lần xuất hiện của ký tự được tính là đúng khi phép gióng hàng mức ký tự giữa
ground truth và prediction (cả hai ở NFC) ghép nó với đúng ký tự đó. Tập 88 chữ
lấy từ `../audit_charset.py`, không gõ tay.

File trong `results/`:

| File | Nội dung |
| --- | --- |
| `recognizer_metrics.csv` | Một dòng cho mỗi recognizer |
| `recognizer_lines.csv` | Số lỗi theo từng dòng và recognizer |
| `missing_characters.csv` | `char, unicode, occurrences, ppocr_correct, ppocr_accuracy, vietocr_correct, vietocr_accuracy` cho cả 88 chữ |
| `recognizer_hard_cases.csv` | Đúng/sai của từng hard case |
| `ppocrv6_head_analysis.json`, `ppocrv6_medium_rec_state_dict.csv` | Từ `inspect_rec_checkpoint.py`, không cần ground truth |

## Quy tắc quyết định

Chỉ áp dụng khi có **ít nhất 100 dòng verified**. Ít hơn thì script in
`WINNER: NOT DECIDED`.

1. Nếu CER của VietOCR thấp hơn đáng kể **và** missing-character accuracy của
   nó cao hơn rõ rệt: đề xuất PaddleOCR detection + VietOCR recognition, và
   fine-tune VietOCR trước.
2. Nếu không, và PP-OCRv6 vẫn cạnh tranh ở các ký tự ngoài nhóm 88: đề xuất dict
   mở rộng + migrate head + fine-tune PP-OCRv6.
3. Nếu không điều kiện nào thoả: không đề xuất.

"Đáng kể" được hiểu là khoảng tin cậy 95% của hiệu số không chứa 0. Khoảng này
tính bằng bootstrap theo cặp trên các dòng (2000 lần lấy mẫu lại, seed cố định):
hai model được chấm trên cùng những dòng được lấy lại, nên khoảng tin cậy phản
ánh khác biệt giữa hai model chứ không phải độ khó của mẫu. "PP-OCRv6 cạnh
tranh" nghĩa là other-character accuracy của nó không thấp hơn VietOCR một cách
đáng kể. Script in cả ba hiệu số kèm khoảng tin cậy, để có thể đánh giá lại nếu
muốn dùng ngưỡng khác.

Lưu ý khi đọc kết quả: điều kiện 1 và điều kiện "PP-OCRv6 cạnh tranh" có thể
cùng đúng. PP-OCRv6 không thể xuất 88 chữ này nên CER của nó trên tiếng Việt
gần như chắc chắn cao hơn; câu hỏi thực sự mà other-character accuracy trả lời
là nó thua *chỉ vì* 88 chữ đó, hay còn vì lý do khác.

## Quan sát trước khi có ground truth

Những điều sau thấy được từ prediction, **chưa phải độ chính xác**:

- `PP-OCRv6_medium_rec` không xuất chữ nào trong nhóm 88 (0 lần trên 364 dòng),
  đúng như từ điển của nó. Chữ bị thiếu thường bị bỏ hẳn:
  `Căn c Lut Ban hành văn bn quy phm pháp lut`.
- VietOCR xuất 2.257 chữ thuộc nhóm 88, trên 336/364 dòng.
- VietOCR đôi khi thêm chữ không có trong ảnh ở đầu hoặc cuối dòng dài, ví dụ
  `…được tháng 19` sau khi dòng đã kết thúc ở chữ `được`.

**Dòng dài và giới hạn 512 px của VietOCR.** VietOCR đưa ảnh về cao 32 px và
rộng tối đa 512 px (tỉ lệ 16:1). 255/364 crop rộng hơn tỉ lệ đó và bị nén ngang;
tỉ lệ trung vị của crop là 26:1. Đã thử nới giới hạn lên 1024 px
(`--image-max-width 1024`, chỉ để chẩn đoán): kết quả tệ hơn rõ, model dừng giữa
dòng (`Căn cứ Luật Ban hành văn bản quy phạm pháp luận`), tổng số ký tự xuất ra
trên các crop này giảm từ 18.901 xuống 10.916. Vì vậy cấu hình gốc được giữ
nguyên làm cấu hình benchmark. Nếu VietOCR được chọn, cắt dòng dài thành đoạn
ngắn hơn trước khi nhận dạng là việc đáng thử ở phase sau.

**Thiết bị.** PyTorch MPS chạy được với VietOCR và cho text giống CPU ở 364/364
dòng, nhưng không nhanh hơn (570 so với 513 ms/crop). Cả hai recognizer vì thế
được đo trên CPU.

| Recognizer | Thiết bị | Crop | Thời gian | Trung bình |
| --- | --- | --- | --- | --- |
| `PP-OCRv6_medium_rec` | CPU (Apple M2) | 364 | 61,6 s | 169 ms/crop |
| VietOCR `vgg_transformer` | CPU (Apple M2) | 364 | 186,7 s | 513 ms/crop |

Thời gian chỉ tính phần nhận dạng, không tính nạp model, và đo trên một máy
đang chạy việc khác; chỉ nên đọc như bậc độ lớn.

## Test

```bash
python -m unittest discover -s benchmarks/vietnamese/tests
```

Bộ test kiểm tra: audit bộ ký tự, dict mở rộng giữ nguyên index, manifest không
trùng id, hai recognizer phủ cùng tập id, evaluator với đáp án biết trước, công
cụ annotation, hình học của crop, `PaddleOCR/` không bị sửa, và không có ảnh,
PDF hay weights nào có thể lọt vào commit.

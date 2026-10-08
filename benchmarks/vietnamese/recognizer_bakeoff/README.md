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

# 4. (người làm) verify ground truth; tự dừng khi đủ 100 dòng
python $B/annotate.py

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
| `annotate.py` | Công cụ verify ground truth: trang web local (mặc định) hoặc terminal (`--cli`) |
| `annotation_store.py` | Trạng thái phiên annotation: thứ tự dòng, lưu, resume, điều kiện dừng |
| `annotation_server.py`, `annotation_page.html` | Trang web local của `annotate.py` (chỉ dùng thư viện chuẩn) |
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

Các file tổng hợp trong `results/` chỉ gồm số liệu và nhãn thì được track:
`summary.json`, `recognizer_metrics.csv`, `line_length_groups.csv`,
`ground_truth_source_groups.csv`, `missing_characters.csv`.

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
id  document  page  crop_path  ppocr_prediction  vietocr_prediction  ground_truth  verified
excluded_reason  ground_truth_source  annotator  verified_at  ground_truth_sha256
```

Tám cột đầu do `select_annotation_subset.py` tạo: `ground_truth` rỗng và
`verified=false` ở mọi dòng, không có prediction nào được copy vào
`ground_truth`. Năm cột sau do `annotate.py` điền. Script chọn mẫu không bao giờ
ghi đè một bảng đã có ground truth hoặc đã có dòng bị bỏ qua.

Một dòng ở đúng một trong ba trạng thái:

| Trạng thái | `verified` | `excluded_reason` | Được tính điểm |
| --- | --- | --- | --- |
| chưa xem | `false` | rỗng | không |
| verified | `true` | rỗng | có |
| bỏ qua | `false` | lý do | không |

## Verify ground truth

```bash
python benchmarks/vietnamese/recognizer_bakeoff/annotate.py          # trang web local
python benchmarks/vietnamese/recognizer_bakeoff/annotate.py --cli    # trong terminal
```

Mặc định, lệnh mở một trang ở `http://127.0.0.1:8765/` hiển thị ảnh crop phóng
to, hai prediction và các nút thao tác. Server chỉ nghe trên `127.0.0.1` và chỉ
dùng thư viện chuẩn của Python; ảnh không rời khỏi máy. `--cli` làm cùng việc
trong terminal, với đúng các phím dưới đây.

| Phím | Ý nghĩa |
| --- | --- |
| `p` | text của PP-OCRv6 khớp chính xác với ảnh |
| `v` | text của VietOCR khớp chính xác với ảnh |
| `e` | gõ, hoặc sửa, đúng text của ảnh rồi lưu |
| `s` | bỏ qua dòng này, kèm lý do |
| `q` | lưu và thoát |
| `u` | hoàn tác thao tác gần nhất của phiên |

`p` và `v` **không** có nghĩa là prediction tự động đúng. Bấm một trong hai là
người làm xác nhận: *tôi đã nhìn ảnh và text này khớp chính xác từng ký tự*.
Không có lựa chọn mặc định nào, và nhấn Enter khi chưa làm gì không lưu gì cả.

Trên trang web, `Shift+P` và `Shift+V` chép một prediction vào ô nhập để sửa
vài ký tự thay vì gõ lại cả dòng; phải nhấn Enter mới lưu. Ở chế độ terminal,
`e` yêu cầu gõ cả dòng rồi xác nhận, và `o` mở ảnh bằng trình xem mặc định (file
`annotation/candidates/_current.png` luôn là crop hiện tại, nên chỉ có một cửa
sổ).

**Ground truth là đúng những chữ in nhìn thấy trên ảnh.**

- Giữ nguyên dấu, chữ hoa/thường, dấu câu, khoảng trắng và cả lỗi chính tả của
  văn bản gốc.
- Không sửa theo suy đoán, không viết lại, không khai triển chữ viết tắt, không
  thêm chữ ảnh không có, không bỏ dấu.
- Hai prediction chỉ để tham khảo: cả hai có thể sai ở cùng một chỗ, nên không
  dựa vào chúng để đoán.
- Ground truth được lưu ở Unicode NFC, bỏ khoảng trắng ở hai đầu.

**Bỏ qua (`s`)** khi không xác định được ground truth đáng tin: chữ ký tay, con
dấu che chữ, dòng không đọc được chắc chắn, crop lỗi nặng. Dòng bị bỏ qua giữ
`verified=false`, được ghi `excluded_reason` và không bao giờ vào CER/WER.

**Thứ tự và điểm dừng.** Các dòng được đưa ra theo thứ tự luân phiên giữa tài
liệu, giữa các trang và giữa các tầng lấy mẫu, nên dừng ở bất kỳ đâu thì tập đã
verified vẫn trải đều. Phiên tự kết thúc khi đủ 100 dòng verified (`--target`),
không cần làm hết 150. Dòng bị bỏ qua không được tính vào 100. Nếu lúc đạt 100
mà còn thiếu một tài liệu, một trang hoặc một loại dòng (heading, body, số hiệu,
dòng dài, dòng ngắn, chữ thuộc nhóm 88, mẫu random), phiên tiếp tục với đúng
các dòng lấp chỗ thiếu đó.

**Lưu và resume.** Bảng được ghi lại sau mỗi thao tác. Đóng terminal hay tắt
máy giữa chừng không mất gì; chạy lại lệnh sẽ tiếp tục ở dòng kế tiếp. Với mỗi
dòng verified, bảng ghi `annotator`, `verified_at`, cách verify
(`ground_truth_source`: `ppocr_accepted`, `vietocr_accepted` hoặc `typed`) và
`ground_truth_sha256` (hash của ground truth ở NFC). Nguyên văn phím gõ và mọi
thao tác, kể cả hoàn tác, nằm trong `annotation/annotation_log.jsonl`.

Một dòng đã verified không bao giờ bị ghi đè trong phiên thường. Muốn sửa thì
gọi đích danh: `annotate.py --id <id>`. Nếu ground truth bị sửa tay trong file
TSV sau khi verify, hash không còn khớp và evaluator sẽ không chấm dòng đó.

**Soát lại các dòng đã chấp nhận.** Chấp nhận nguyên văn một prediction là cách
verify nhanh nhất và cũng dễ sót nhất: mắt dễ bỏ qua một dấu thanh, một chữ hoa
hay một dấu câu khi text trông đã đúng. Mỗi lần sót như vậy làm model được chấp
nhận có điểm cao hơn thực tế, vì ground truth khi đó chép lại lỗi của nó.
`evaluate_recognizers.py` in riêng kết quả theo cách verify để thấy mức phụ
thuộc này, và có thể duyệt lại toàn bộ các dòng đó:

```bash
python benchmarks/vietnamese/recognizer_bakeoff/annotate.py --recheck vietocr_accepted
```

Mỗi dòng hiện lại kèm ground truth đang lưu trong ô nhập: sửa rồi nhấn Enter,
hoặc bấm `v` để xác nhận lại rằng nó khớp.

## Chỉ số

`evaluate_recognizers.py` chỉ dùng các dòng `verified=true` có hash khớp. Khi
chưa có dòng nào, nó in `CER/WER: PENDING HUMAN-VERIFIED GROUND TRUTH` và không
ghi file kết quả.

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

**So sánh theo cặp.** Hai model chạy trên cùng crop và cùng ground truth, nên
mỗi dòng cho một cặp kết quả: model nào ít lỗi ký tự hơn thì thắng dòng đó.
Script báo số dòng mỗi bên thắng, số dòng hoà, trung bình và trung vị của hiệu
CER theo dòng (VietOCR trừ PP-OCRv6, âm là VietOCR tốt hơn), và khoảng tin cậy
95% của hiệu micro CER, tính bằng bootstrap theo cặp (2000 lần lấy mẫu lại các
dòng, seed cố định). Một khác biệt chỉ được gọi là rõ khi khoảng này không chứa
0.

**Theo độ dài dòng.** Dòng được chia theo tỉ lệ rộng/cao của crop, vì đó là thứ
giới hạn 512 px của VietOCR tác động vào (VietOCR đưa ảnh về cao 32 px, rộng tối
đa 512 px):

| Nhóm | Tỉ lệ rộng/cao | Với VietOCR |
| --- | --- | --- |
| `short` | tới 16:1 | không bị nén |
| `medium` | trên 16:1 tới 24:1 | bị nén ngang tới 1,5 lần |
| `long` | trên 24:1 | bị nén hơn 1,5 lần |

**Chèn chữ ở đầu/cuối dòng.** Để đo hiện tượng VietOCR bịa chữ ở hai đầu dòng
dài, script tìm phần đuôi của prediction nằm sau điểm mà prediction khớp tốt
nhất với toàn bộ ground truth (và tương tự cho phần đầu). Chỉ báo trường hợp rõ
ràng: phần thừa có ít nhất 3 ký tự nhìn thấy được, và phần còn lại của
prediction khác ground truth không quá 50%. Một ký tự cuối bị nhận sai là thay
thế, không phải chèn. Phép đo này bỏ sót các phần thừa ngắn hơn 3 ký tự, nên con
số là cận dưới.

File trong `results/` (chỉ nằm trên máy, xem mục "Trong git và ngoài git"):

| File | Nội dung |
| --- | --- |
| `summary.json` | Mọi con số của báo cáo, kèm thành phần của tập ground truth |
| `recognizer_metrics.csv` | Một dòng cho mỗi recognizer |
| `recognizer_lines.csv` | Số lỗi theo từng dòng và recognizer |
| `missing_characters.csv` | `char, unicode, occurrences, ppocr_correct, ppocr_accuracy, vietocr_correct, vietocr_accuracy` cho cả 88 chữ |
| `recognizer_hard_cases.csv` | Đúng/sai của từng hard case |
| `line_length_groups.csv` | CER/WER theo nhóm độ dài |
| `edge_insertions.csv` | Các trường hợp chèn chữ ở đầu/cuối dòng |
| `recognizer_errors.csv` | Ground truth và hai prediction của từng dòng, dòng nhiều lỗi nhất ở trên |
| `ppocrv6_head_analysis.json`, `ppocrv6_medium_rec_state_dict.csv` | Từ `inspect_rec_checkpoint.py`, không cần ground truth |

## Quy tắc quyết định

Chỉ áp dụng khi có **ít nhất 100 dòng verified**. Ít hơn thì script in
`WINNER: NOT DECIDED`.

**Chọn VietOCR** khi cả bốn điều sau đúng:

1. CER thấp hơn PP-OCRv6 rõ rệt;
2. WER thấp hơn;
3. accuracy trên 88 chữ thiếu vượt trội;
4. VietOCR không tệ hơn PP-OCRv6 một cách rõ rệt trên nhóm dòng `long`.

Kiến trúc tiếp theo: `PP-OCRv6_medium_det` → line crop → VietOCR.

**Chọn PP-OCRv6 tuỳ biến** khi cả bốn điều sau đúng:

1. PP-OCRv6 gần VietOCR xét toàn bộ (CER của VietOCR không thấp hơn rõ rệt);
2. lỗi của PP-OCRv6 tập trung ở 88 chữ thiếu (other-character accuracy của nó
   không thấp hơn VietOCR rõ rệt);
3. VietOCR tệ hơn rõ rệt trên nhóm dòng `long`;
4. việc migrate head đã được chứng minh (`results/ppocrv6_head_analysis.json`).

Kiến trúc tiếp theo: `PP-OCRv6_medium_det` → `PP-OCRv6_medium_rec` với charset mở
rộng, head đã migrate, và fine-tune.

**Còn lại là chưa ngã ngũ:** không train; verify nốt các dòng còn lại rồi đánh
giá lại trên toàn bộ.

"Rõ rệt" và "vượt trội" đều được hiểu là khoảng tin cậy 95% của hiệu số (bootstrap
theo cặp) không chứa 0; riêng WER chỉ so điểm ước lượng. Script in từng điều
kiện kèm hiệu số và khoảng tin cậy, để có thể đánh giá lại với ngưỡng khác.

## Kết quả trên 100 dòng đã verified

Đánh giá ngày 2026-10-08, trên 100 dòng do người verify (4.853 ký tự, 1.053 từ,
3 tài liệu, 9 trang, tất cả ở NFC). Số liệu đầy đủ: `results/summary.json`.

| | `PP-OCRv6_medium_rec` | VietOCR `vgg_transformer` |
| --- | --- | --- |
| CER (raw = NFC) | 13,06% | **4,51%** |
| WER (raw = NFC) | 53,47% | **8,83%** |
| Dòng đúng hoàn toàn | 3% | **57%** |
| 88 chữ thiếu, đúng / 487 lần xuất hiện | 0 (0%) | **470 (96,51%)** |
| Ký tự khác, đúng / 4.366 | 96,93% | **98,26%** |
| CER dòng `short` (38 dòng) | 16,65% | **5,43%** |
| CER dòng `medium` (21 dòng) | 12,14% | **5,07%** |
| CER dòng `long` (41 dòng) | 12,36% | **4,07%** |
| Dòng có chèn chữ rõ ràng ở đầu/cuối | **0** | 9 |
| Lỗi: thay / xoá / chèn | 172 / 449 / 13 | 76 / 17 / 126 |

So sánh theo cặp: VietOCR ít lỗi hơn ở 81 dòng, PP-OCRv6 ở 14 dòng, hoà 5 dòng.
Hiệu micro CER (VietOCR trừ PP-OCRv6) là −8,55 điểm phần trăm, khoảng tin cậy
95% từ −10,47 tới −6,45, không chứa 0.

**Quyết định:** `PP-OCRv6_medium_det` → line crop dùng chung → VietOCR. Cả bốn
điều kiện chọn VietOCR ở mục trên đều đạt. Không theo hướng train PP-OCRv6 tuỳ
biến ở giai đoạn này.

Ba điều cần nhớ khi dùng các con số này:

- **Con số của VietOCR có phần lạc quan.** 57 dòng được verify bằng cách chấp
  nhận nguyên văn text của VietOCR, và trên các dòng đó nó có 0 lỗi theo định
  nghĩa. Soi ngẫu nhiên 12 trong 57 dòng với ảnh thấy 5 dòng không khớp hẳn
  (hoa/thường, dấu thanh, dấu câu). Trên riêng 41 dòng gõ tay, CER là 9,69% so
  với 12,64% của PP-OCRv6 và khoảng tin cậy của hiệu có chứa 0. Chiều của kết
  luận không đổi: muốn hai model ngang nhau thì mỗi dòng đã chấp nhận phải che
  hơn 7 lỗi. Có thể soát lại bằng `annotate.py --recheck vietocr_accepted`.
- **Điểm yếu chính của VietOCR là chèn chữ, không phải đọc sai.** 126 trong 219
  lỗi ký tự của nó là ký tự chèn, gần như toàn bộ nằm ở hai đầu của dòng `long`
  và `medium`, tức những dòng bị nén ngang.
- **PP-OCRv6 thua chủ yếu vì 88 chữ.** 487 trong 634 lỗi của nó nằm đúng ở các
  chữ đó.

100 dòng này đã được đóng băng với tên **`bakeoff_regression`**. Chúng đã chọn
ra recognizer và lỗi trên chúng đã định hình danh sách hard case, nên chúng
dùng để phát hiện regression và so sánh với các con số ở trên, **không phải là
blind test** và không phải thước đo chất lượng cuối cùng. Con số cuối cùng sẽ
được đo trên tài liệu mới; xem `datasets/vietnamese_recognition/README.md`.

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

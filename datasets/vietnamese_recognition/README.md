# Dataset nhận dạng dòng chữ tiếng Việt

Dữ liệu để fine-tune recognizer VietOCR cho văn bản hành chính tiếng Việt, và
các tập dùng để đo kết quả.

Kiến trúc đã chốt sau bake-off: `PP-OCRv6_medium_det` → line crop dùng chung →
VietOCR. Thư mục này chuẩn bị dữ liệu và chứa script train
(`train_vietocr.py`). **Mới chỉ chạy smoke train; chưa có lần train đầy đủ
nào.** Cách train, baseline và kế hoạch GPU: `configs/vietnamese/vietocr/README.md`.

## Sáu tập

| Tập | Nguồn | Dùng để | Hiện có |
| --- | --- | --- | --- |
| `real_train` | tài liệu mới, người verify | train | 0 dòng |
| `real_val` | tài liệu mới, người verify | **chọn checkpoint, chọn width, chọn mọi tham số** | 0 dòng |
| `synthetic_train` | sinh ra | train | 5.059 dòng |
| `synthetic_val` | sinh ra | chẩn đoán: model đã học được dữ liệu tổng hợp chưa | 552 dòng |
| `bakeoff_regression` | 3 tài liệu benchmark | regression, so sánh với bake-off, các ca khó đã biết | 100 dòng, đóng băng |
| `blind_test` | tài liệu mới, người verify | con số cuối cùng, xem **một lần** | 0 dòng, đang khoá |

Hai quy tắc xuyên suốt mọi script:

- **Một tài liệu gốc thuộc đúng một tập**, cùng với mọi dòng của nó.
- **Dòng của tập đánh giá đã đóng băng không bao giờ vào train hay validation.**

```text
datasets/vietnamese_recognition/
├── real_source/          thả tài liệu mới vào đây      (không vào git)
├── real_documents.tsv    sổ đăng ký tài liệu: id, SHA-256, split
├── real_work/            crop, prediction tham khảo, bảng annotation (không vào git)
├── bakeoff_regression/   100 dòng đã đóng băng + SHA-256 của 3 tài liệu benchmark
├── blind_test/           tập blind sau khi đóng băng   (chưa có)
├── legacy_candidates/    259 dòng cũ chưa verify       (không vào git, không dùng)
├── train/, val/          ảnh tổng hợp                  (sinh ra, không vào git)
├── manifests/            sáu manifest, báo cáo, hard_cases.txt
├── lexicon/              từ vựng hành chính cho bộ sinh câu
└── *.py, tests/
```

## `bakeoff_regression`: 100 dòng của bake-off

100 dòng do người verify trong bake-off (4.853 ký tự, 1.053 từ, 3 tài liệu, 9
trang) **không phải là blind test**, vì:

- chính chúng đã chọn ra recognizer;
- lỗi của VietOCR trên chúng đã được dùng để lập danh sách hard case;
- 57 dòng được chấp nhận nguyên văn từ VietOCR, và soi thử 12 dòng trong số đó
  thấy 5 dòng có vẻ không khớp hẳn với ảnh: ground truth hơi thiên về VietOCR
  gốc.

Chúng được giữ nguyên, không xoá, không sửa nhãn, và dùng cho ba việc: phát
hiện regression, so sánh với số liệu bake-off, theo dõi các ca khó đã biết.
**Không dùng làm con số chất lượng cuối cùng.**

`bakeoff_regression/bakeoff_regression.tsv`:

```text
id  document  page  line_index  ground_truth  crop_sha256  split  frozen  blind
```

Mọi dòng có `split=bakeoff_regression`, `frozen=true`, `blind=false`. File
không chứa ảnh: `id` và `crop_sha256` gắn ground truth với đúng một file crop.

Việc đổi tên từ `test_holdout` không đổi một nhãn nào: digest tính trên
(id, ground truth, hash crop) của 100 dòng trước và sau khi đổi là một,
`c8d06be9…6b83ca5a`, và được ghim trong `tests/test_frozen_sets.py`.

| Ở đâu | Làm gì |
| --- | --- |
| `bakeoff_regression.sha256` | SHA-256 của file lúc đóng băng. Mọi script đọc tập này đều kiểm tra, lệch là dừng. |
| `freeze_evaluation_set.py` | Không có lệnh nào ghi lại tập này. |
| `build_dataset.py` | Không ghi dòng nào có id hoặc ảnh của tập này vào tập khác; dòng tổng hợp không lặp nguyên văn text của nó. |
| `audit_dataset.py` | **FAIL** nếu tập khác có id hoặc ảnh của nó, hoặc manifest của nó khác bản đóng băng. |
| `tests/test_frozen_sets.py` | Ghim SHA-256 của file và digest của nhãn. |

```bash
python datasets/vietnamese_recognition/freeze_evaluation_set.py --check
```

## Tài liệu thật mới

Dữ liệu thật cho train, validation và blind test phải đến từ **tài liệu khác**
3 tài liệu benchmark (`21-bct.signed.pdf`, `216-tb.signed.pdf`,
`738-ttg.signed.pdf`). Nhận PDF, PNG, JPEG, TIFF.

```bash
# 1. Thả file vào datasets/vietnamese_recognition/real_source/, rồi đăng ký
python datasets/vietnamese_recognition/import_real_documents.py --note "nguồn của lô này"

# 2. Detect và cắt dòng, một lần cho mỗi tài liệu (môi trường .venv)
python datasets/vietnamese_recognition/export_real_line_crops.py

# 3. Chia TÀI LIỆU vào train / val / blind
python datasets/vietnamese_recognition/assign_document_splits.py

# 4. Chọn dòng cho người verify
python datasets/vietnamese_recognition/select_real_lines.py

# 5. Verify (lưu sau mỗi dòng; chạy lại lệnh để làm tiếp)
python datasets/vietnamese_recognition/annotate_split.py blind_test
python datasets/vietnamese_recognition/annotate_split.py real_val
python datasets/vietnamese_recognition/annotate_split.py real_train

# 6. Đóng băng blind test khi đủ 100 dòng, trước khi chọn bất cứ thứ gì
python datasets/vietnamese_recognition/freeze_evaluation_set.py blind_test

# 7. Đưa dòng đã verify vào manifest, rồi audit
python datasets/vietnamese_recognition/build_dataset.py --skip-synthetic
python datasets/vietnamese_recognition/audit_dataset.py
```

### 1. Đăng ký tài liệu

`real_documents.tsv`, mỗi tài liệu một dòng:

| Cột | Ý nghĩa |
| --- | --- |
| `document_id` | `doc_` + 12 chữ số hex đầu của SHA-256 |
| `filename` | tên lúc import; chỉ để người đọc |
| `sha256` | của file. **Đây là danh tính của tài liệu, không phải tên file.** |
| `page_count`, `file_type` | loại file nhận theo nội dung, không theo đuôi |
| `source_note` | ghi chú nguồn; sửa tay được, import lại vẫn giữ |
| `split`, `blind` | do bước 3 điền |

- File trùng SHA-256 với một tài liệu benchmark bị **từ chối**, đổi tên cũng vậy.
- Cùng nội dung dưới hai tên là một tài liệu.
- `real_source/` nằm trong `.gitignore`; script chỉ đọc file ở đó.

### 2. Cắt dòng

Dùng đúng pipeline detection đã đóng băng trong bake-off, **không đổi ngưỡng**:

```text
PP-OCRv6_medium_det
use_doc_orientation_classify = true
use_doc_unwarping            = false
use_textline_orientation     = true
limit_side_len 64 (min), thresh 0.3, box_thresh 0.6, unclip_ratio 1.5
```

Trang nào được detect với tham số khác thì việc export dừng lại. Mỗi tài liệu
chỉ được cắt một lần. `real_work/manifest.jsonl` ghi cho mỗi crop: `id`,
`document_id`, `page`, `line_index`, `polygon`, `crop_path`, `crop_sha256`,
`width`, `height`, `aspect_ratio`.

Prediction của PP-OCRv6 và VietOCR được lưu làm **tham khảo cho người verify**.
Chúng không bao giờ là nhãn; không có pseudo-label.

Bước này cũng so text nhận dạng được giữa các tài liệu: hai tài liệu chung từ
50% số dòng (một văn bản scan hai lần, hoặc một tài liệu benchmark scan lại) được
ghi vào `real_work/document_similarity.json` và lệnh trả mã lỗi. SHA-256 không
bắt được trường hợp này.

### 3. Chia theo tài liệu

Chia theo **cả tài liệu**, không theo trang hay dòng:

| Tập | Số tài liệu | Mục tiêu dòng đã verify |
| --- | --- | --- |
| blind | 20% số tài liệu, ít nhất 2 | khoảng 100 |
| val | 20% số tài liệu, ít nhất 2 | khoảng 100 |
| train | phần còn lại (6–8 khi có 10–12 tài liệu) | khoảng 400 |

Thứ tự xếp lấy từ hash nội dung, không liên quan tới tên, ngày hay nội dung của
tài liệu: không ai nhìn vào một tài liệu để quyết định nó đi đâu. Tài liệu đã
được xếp thì các lần chạy sau không đổi nữa. `--set <document_id>=<split>` cho
phép chuyển tay, và bị từ chối ngay khi tài liệu đã có một dòng được annotate.

Nếu hai tài liệu của blind hoặc val có dưới 130 dòng detect được, script báo
rằng có thể không đủ 100 dòng verify. Cách giải quyết là thêm tài liệu, không
phải chuyển dòng giữa các tập.

### 4. Chọn dòng

| Tập | Số dòng bày ra | Cách chọn |
| --- | --- | --- |
| `real_train` | 520 | phân tầng, **30% rút ngẫu nhiên đều** (không bao giờ dưới 25%) |
| `real_val` | 140 | ngẫu nhiên đều |
| `blind_test` | 140 | ngẫu nhiên đều, không nhìn vào nội dung dòng |

Các tầng của `real_train`: tiêu đề 8%, ngày tháng 5%, số hiệu văn bản 6%, tên cơ
quan 5%, tên riêng 5%, dòng dài 7%, dòng ngắn 5%, nhiều dấu câu 4%, số và ký hiệu
5%, dấu chồng 6%, chất lượng kém 4%, thân văn bản 10%, ngẫu nhiên 30%. Tầng được
đoán từ prediction tham khảo và từ crop, chỉ để lái việc lấy mẫu. Phần ngẫu nhiên
giữ cho chữ thường ngày có mặt đúng với tần suất thật: một bộ train chỉ gồm ca
khó sẽ dạy model rằng mọi dòng đều khó.

Số dòng bày ra nhiều hơn mục tiêu vì một số crop sẽ bị bỏ qua (chữ ký, con dấu,
không đọc được).

### 5. Verify

`annotate_split.py` mở lại trang annotation của bake-off: ảnh crop phóng to, hai
prediction tham khảo, ô ground truth. Thao tác: nhận text VietOCR, nhận text
PP-OCRv6, sửa, gõ mới, bỏ qua, undo, lưu và thoát. **Không có gì được chấp nhận
tự động.** Lệnh tự dừng khi đủ mục tiêu (400 / 100 / 100).

Với `blind_test`, hai prediction **bị ẩn mặc định** và mọi dòng được gõ từ ảnh.
Chấp nhận text của model là cách verify nhanh nhất và cũng là cách dễ bỏ sót một
dấu sai nhất; ở bake-off điều đó đã làm ground truth nghiêng về model được chép.
Blind test không được nghiêng về model nào. `--show-predictions` bật lại nếu
muốn.

Dòng có ký tự ngoài vocab của VietOCR (gạch dài `–`, ngoặc kép cong, `…`) vẫn
được giữ đúng như trên giấy. Trong manifest nó mang `subset=out_of_vocabulary`,
không vào file train/val của VietOCR và không được tính vào điều kiện sẵn sàng.

## Quy trình blind test

Tài liệu blind được đánh dấu `blind=true` trong sổ đăng ký, và mọi dòng của
chúng mang `blind=true` trong manifest.

Chúng **không được ảnh hưởng tới**: text tổng hợp, danh sách hard case,
hyperparameter, vocab, việc chọn width, việc chọn epoch/checkpoint,
augmentation. Cụ thể trong code:

| Ở đâu | Làm gì |
| --- | --- |
| `select_real_lines.py` | Rút dòng blind ngẫu nhiên, không tính tầng nào trên nội dung của chúng. |
| `annotate_split.py` | Ẩn prediction khi verify blind. |
| `build_dataset.py` | Bộ sinh text không đọc tập blind. Không ghi file dạng VietOCR cho tập blind và tập regression, nên không config nào trỏ vào được. |
| `audit_dataset.py` | Về tập blind chỉ báo số dòng và số tài liệu. Không độ phủ chữ, không phân bố độ dài, không bảng resize. |
| `evaluate_splits.py` | Mặc định không lấy crop blind và **không tính điểm blind**, kể cả khi file prediction có sẵn chúng: in `blind_test: LOCKED`. |
| `check_vietocr_config.py` | Từ chối config có dòng blind hoặc regression trong file train/val, hoặc có file validation không phải toàn dòng thật. |
| config | `selection_split: real_val`, `blind_test_used_for_selection: false`. |

Mở khoá cho đúng một lần chạy:

```bash
python datasets/vietnamese_recognition/evaluate_splits.py score \
  --predictions <predictions.jsonl> --label <tên model> \
  --unlock-blind-test --reason "đo lần cuối config đã chọn"
```

Mỗi lần mở khoá ghi một dòng vào `manifests/blind_test_unlocks.jsonl`: ai, lúc
nào, model nào, vì sao. Audit in số lần đã xem. **Hiện tại: 0 lần.**

Khoá này là quy trình, không phải bảo mật: ai cũng đọc được file TSV. Mục đích
là không ai vô tình chỉnh gì theo blind test, và mọi lần xem đều để lại dấu.

Sau khi `freeze_evaluation_set.py blind_test` chạy, tập blind là đúng những gì
file đóng băng ghi; dòng verify thêm sau đó không lọt vào.

## Đánh giá theo từng tập

```bash
python datasets/vietnamese_recognition/evaluate_splits.py inputs --output <inputs.jsonl>
.venv-vietocr/bin/python benchmarks/vietnamese/recognizer_bakeoff/run_vietocr.py \
  --config configs/vietnamese/vietocr/exp_a_width512.yml \
  --manifest <inputs.jsonl> --output <predictions.jsonl>
python datasets/vietnamese_recognition/evaluate_splits.py score \
  --predictions <predictions.jsonl> --label <tên model>
```

CER, WER và tỉ lệ dòng đúng hoàn toàn được báo **riêng** cho `real_val`,
`synthetic_val`, `bakeoff_regression`, và `blind_test` (khi mở khoá); kết quả ghi
vào `manifests/evaluations/<label>.json`.

Mốc so sánh hiện có, model pretrained trên `bakeoff_regression` (đúng bằng số
liệu bake-off):

| Model | CER (NFC) | WER (NFC) | Dòng đúng hoàn toàn |
| --- | --- | --- | --- |
| VietOCR `vgg_transformer` | 4,51% | 8,83% | 57% |
| PP-OCRv6_medium_rec | 13,06% | 53,47% | 3% |

## Validation và chọn checkpoint

- Validation dùng để chọn là `real_val`: **toàn dòng thật**, từ tài liệu không
  có mặt trong train.
- Checkpoint, width và mọi tham số được chọn theo **CER trên `real_val`**
  (hoà thì theo WER). Không chọn theo `synthetic_val` một mình, không bao giờ
  theo `blind_test`.
- `synthetic_val` chỉ để chẩn đoán: CER tổng hợp giảm mà CER thật không giảm
  nghĩa là model đang thuộc font.

## Trộn dữ liệu thật và tổng hợp

Vài trăm dòng thật sẽ chìm giữa vài nghìn dòng tổng hợp nếu trộn nguyên. Cách
trộn nằm trong `configs/vietnamese/vietocr/data_mix.yml`, không nằm trong code:

```yaml
real_to_synthetic: [1, 2]     # tỉ lệ mẫu thật : tổng hợp trong một lượt
method: oversample_real       # hoặc subsample_synthetic
max_real_repeats: 10
seed: 20261201
```

- `oversample_real`: lặp mỗi dòng thật cho tới khi đạt tỉ lệ, giữ mọi dòng tổng
  hợp. Với 400 dòng thật và 5.059 dòng tổng hợp: mỗi dòng thật 6 lần, 2.400 +
  5.059 = 7.459 mẫu, dòng thật chiếm 32%.
- `subsample_synthetic`: giữ mỗi dòng thật một lần, chỉ rút số dòng tổng hợp mà
  tỉ lệ cho phép (400 + 800).

Đổi một giá trị rồi chạy `build_dataset.py --skip-synthetic` là có
`manifests/vietocr/train_mix_annotation.txt` mới. Manifest của các tập không bị
việc trộn thay đổi, nên tỉ lệ nào cũng đổi lại được.

## Manifest chuẩn

Mỗi tập một file TSV thuần (không quote, field không chứa tab) trong
`manifests/`: `real_train.tsv`, `real_val.tsv`, `synthetic_train.tsv`,
`synthetic_val.tsv`, `bakeoff_regression.tsv`, `blind_test.tsv`.

| Cột | Ý nghĩa |
| --- | --- |
| `id` | Định danh duy nhất trong toàn bộ dataset |
| `source_document` | `document_id` của tài liệu gốc; với dòng tổng hợp là `synthetic/<tên dataset>` |
| `page`, `line_index` | Vị trí trong tài liệu gốc; rỗng với dòng tổng hợp |
| `image_path` | Đường dẫn ảnh, tương đối so với thư mục này |
| `text` | Nhãn, UTF-8 NFC |
| `split` | Một trong sáu tập |
| `source_type` | `real`, `synthetic` hoặc `hard_case` |
| `verified` | `true` khi nhãn chắc chắn đúng: dòng thật đã được người verify, hoặc dòng tổng hợp (nhãn chính là text đã vẽ) |
| `crop_sha256` | SHA-256 của file ảnh |
| `image_width`, `image_height` | Kích thước ảnh (pixel) |
| `subset` | `long_line`, `coverage`, `out_of_vocabulary` hoặc rỗng |
| `font` | Font đã vẽ (dòng tổng hợp) |
| `clean_image_path` | Ảnh sạch trước augmentation (dòng tổng hợp) |
| `blind` | `true` chỉ với dòng của `blind_test` |

`manifests/vietocr/*_annotation.txt` là bốn tập train/validation và bản trộn
`train_mix` ở định dạng VietOCR đọc (`đường dẫn ảnh<TAB>nhãn`).

## 259 dòng cũ: `legacy_candidate`

364 crop của bake-off đều từ 3 tài liệu benchmark. 100 dòng là
`bakeoff_regression`; bỏ thêm 5 crop là "bản sao text" của một dòng trong số đó
(cùng một tiêu đề lặp lại ở trang khác), còn **259 dòng chưa có nhãn**.

Chúng nằm trên chính các trang của tập regression, nên train trên chúng sẽ biến
tập regression thành phép đo mức thuộc 3 tài liệu này. Vì vậy:

- chúng được đánh dấu `legacy_candidate`, `usable_for_training: false`
  (`legacy_candidates/candidates_report.json`);
- **không bị xoá, không được annotate, không script nào đưa chúng vào tập nào**;
- audit **FAIL** nếu một dòng trong số đó xuất hiện trong bất kỳ tập nào.

## Dữ liệu tổng hợp

`text_generator.py` sinh dòng chữ theo phong cách văn bản hành chính từ từ vựng
trong `lexicon/administrative.txt`: tên cơ quan, tỉnh thành, tên luật, loại văn
bản, cụm động từ và danh từ quen dùng, chức danh, họ tên. Từ vựng là kiến thức
chung; không có câu nào lấy từ tài liệu benchmark hay tài liệu blind, và không
câu nào được lưu sẵn nguyên vẹn.

| Loại dòng | Tỉ trọng | Ví dụ về dạng |
| --- | --- | --- |
| `body` | 46% | một dòng của đoạn văn nhiều câu |
| `heading` | 9% | tên loại văn bản, tên cơ quan in hoa, trích yếu, `Chương II` |
| `legal_basis` | 8% | `Căn cứ Luật … ngày … tháng … năm …;` |
| `document_number` | 6% | `Số: 15/2024/NĐ-CP`, `V/v …` |
| `recipient` | 6% | `Nơi nhận:`, `- Lưu: VT, …` |
| `article` | 6% | `Điều 3. Hiệu lực thi hành` |
| `date_place` | 5% | `Hà Nội, ngày … tháng … năm …`, thời gian ký số |
| `signature` | 5% | `KT. BỘ TRƯỞNG`, họ tên người ký |
| `figures` | 5% | số tiền, tỉ lệ phần trăm, mã số, số hiệu văn bản |
| `contact` | 4% | `Người ký: …`, `Email: …@….gov.vn` |

Dòng `body` được tạo như cách một recognizer gặp nó: sinh một đoạn 2–4 câu, ngắt
dòng theo một độ rộng ngẫu nhiên, rồi giữ lại một dòng. Dòng đó thường bắt đầu
hoặc kết thúc giữa câu, giống crop của một dòng trên trang thật. Điều này quan
trọng với lỗi bịa chữ: model phải học rằng dòng có thể dừng ở bất cứ đâu.

Bảo đảm của bộ sinh, đều có test:

- **Tái lập được.** Cùng seed và cùng chỉ số cho ra cùng dòng chữ.
- **Đủ bộ chữ.** Sau khi sinh, script đếm từng chữ trong 178 chữ cái tiếng Việt
  (gồm cả 88 chữ PP-OCRv6 thiếu) và sinh thêm dòng cho tới khi chữ hiếm nhất đạt
  ngưỡng (30 lần ở train).
- **Chỉ dùng ký tự model mã hoá được.** Vocab của VietOCR pretrained được giữ
  nguyên, nên nhãn chỉ gồm 229 ký tự của nó.
- **Không cắt cụt.** Nhãn dài nhất 120 ký tự, do cách ngắt dòng chứ không phải
  do cắt. Decoder chạy tối đa 128 bước, theo `decoder_max_seq_length` của
  config (xem "Giới hạn decode" trong README của config).
- **Không lặp text của tập regression.** Mặc định bộ sinh bỏ qua mọi dòng trùng
  nguyên văn với một dòng `bakeoff_regression`. Ba dòng mẫu quen thuộc
  (`QUYẾT ĐỊNH`, `QUYẾT ĐỊNH:`, `Độc lập - Tự do - Hạnh phúc`) nằm trong tập đó
  nên không xuất hiện đứng riêng trong train; các từ đó vẫn có mặt trong những
  dòng khác. Muốn cho phép thì dùng `--allow-regression-texts`.
- **Không biết gì về tập blind.** Bộ sinh không nhận danh sách text nào từ tập
  blind, kể cả để tránh trùng: một danh sách cấm cũng là một cách để tập blind
  định hình dữ liệu train. Trùng text giữa hai tập vì thế chỉ là cảnh báo của
  audit.
- **Validation tách khỏi train.** Seed khác, và không dòng nào trùng text.

### Font

Chỉ dùng font có sẵn trên hệ thống, và chỉ sau khi kiểm tra bằng code rằng font
vẽ được **mọi** ký tự của vocab (`fonts.py`): mỗi ký tự được render và so với
hình "thiếu glyph" của chính font đó.

Trên máy này 22 font được nhận và 8 bị loại. Arial Narrow và Trebuchet MS thiếu
92 chữ tiếng Việt dù hiển thị tiếng Anh bình thường; đây chính là loại lỗi phép
kiểm tra nhằm chặn, vì một glyph thiếu sẽ tạo ra ảnh ô vuông với nhãn là chữ.

| Họ font | Tỉ lệ trong bộ pilot |
| --- | --- |
| Times New Roman | 58,3% |
| Arial | 20,5% |
| Tahoma | 6,9% |
| Georgia | 5,5% |
| Verdana | 5,3% |
| Courier New | 3,5% |

22,7% số dòng in đậm, 9,1% in nghiêng; tiêu đề in hoa thường đậm, dòng ngày
tháng và căn cứ pháp lý thường nghiêng, như trong văn bản thật.

### Augmentation

`render.py` tạo hai ảnh cho mỗi mẫu: ảnh sạch (`clean/`) và ảnh đã làm giống văn
bản scan (`images/`). Cả hai xác định hoàn toàn bởi seed của dataset và id của
mẫu, không phụ thuộc thứ tự sinh.

| Bước | Xác suất | Mức độ |
| --- | --- | --- |
| Nét dày/mảnh | 30% | kernel 2×2; chỉ với dòng cao từ 20 px, chỉ làm mảnh font đậm |
| Nghiêng nhẹ | 45% | tối đa 1,2° và tối đa 6 px lệch ở cuối dòng |
| Nhị phân hoá (scan 1-bit) | 20% | trên ảnh còn sắc nét |
| Giảm độ phân giải | 40% | còn 58–92%, tuỳ cỡ chữ |
| Blur | 30–55% | σ 0,3–0,9, tuỳ cỡ chữ |
| Tông mực và giấy | luôn | mực 0–75, giấy 212–255 |
| Nhiễu scanner | luôn | σ 1–9; 25% có thêm đốm bụi |
| Nén JPEG | 65% | chất lượng 30–90 |

Không có phép bẻ cong hay kéo giãn chữ: một trang giấy phẳng không bị như vậy.
Mức phá chi tiết giảm theo chiều cao dòng, vì chữ nhỏ chịu kém hơn: một ảnh
không đọc được nhưng có nhãn tự tin còn tệ hơn không có mẫu.

**Kiểm tra độ khó.** Cho VietOCR pretrained (chỉ inference) đọc 120 dòng
validation tổng hợp:

| Ảnh | CER | Dòng có chèn chữ ở đầu/cuối |
| --- | --- | --- |
| tổng hợp, sạch | 2,6% | 4 / 120 |
| tổng hợp, đã augment | 5,1% | 17 / 120 |
| 100 dòng `bakeoff_regression` | 4,5% | 9 / 100 |

Ảnh đã augment khó ngang crop thật, và model mắc đúng các kiểu lỗi đã thấy trên
dữ liệu thật: đổi hoa/thường ở dòng `Cơ quan: …`, bỏ `./.` ở cuối, thêm chữ ở
hai đầu dòng. Các dòng sai nặng nhất đều có ảnh đọc được.

## Dòng dài và chiều rộng ảnh

VietOCR đưa ảnh về cao 32 px và rộng tối đa 512 px, nên mọi dòng có tỉ lệ
rộng/cao trên 16:1 bị nén ngang. Trong bake-off, 9 dòng VietOCR bịa chữ ở hai
đầu đều là dòng bị nén.

Bộ pilot có một tập con `long_line` gồm 1.000 dòng train và 100 dòng validation
dài từ 76 ký tự. Manifest ghi chiều rộng, chiều cao và số ký tự của từng dòng.

| | `synthetic_train` | `synthetic_val` | `bakeoff_regression` |
| --- | --- | --- | --- |
| Tỉ lệ tới 16:1 | 2.154 | 227 | 38 |
| 16:1 tới 24:1 | 1.573 | 177 | 21 |
| 24:1 tới 32:1 | 751 | 84 | 40 |
| Trên 32:1 | 581 | 64 | 1 |
| Nhãn từ 91 ký tự | 741 | 83 | 0 |
| Nhãn dài nhất | 119 | 118 | 81 |

Số pixel chiều ngang còn lại cho mỗi ký tự sau khi VietOCR resize về cao 32 px,
theo chiều rộng tối đa:

| Rộng tối đa | Regression: dòng bị nén | Regression: trung vị / phân vị 5 (px/ký tự) | Train tổng hợp: dòng bị nén | Train tổng hợp: trung vị / phân vị 5 |
| --- | --- | --- | --- | --- |
| 512 (pretrained) | 62 / 100 | 10,2 / 6,5 | 2.904 / 5.059 | 9,9 / 4,7 |
| 768 | 41 / 100 | 11,8 / 9,7 | 1.331 / 5.059 | 11,1 / 7,1 |
| 1024 | 1 / 100 | 12,7 / 11,0 | 580 / 5.059 | 11,4 / 8,6 |
| 1280 | 0 / 100 | 12,7 / 11,0 | 120 / 5.059 | 11,6 / 8,6 |

Các con số này gợi ý rằng 1024 px có lợi cho dòng dài, nhưng đó là **giả
thuyết**: model pretrained chưa từng thấy ảnh rộng hơn 512 px. **Chưa chọn
width.** Hai config giống hệt nhau trừ `image_max_width` (512 và 1024) sẽ được
train và so trên `real_val`; xem `configs/vietnamese/vietocr/README.md`. Bảng
này sẽ có thêm `real_train` và `real_val` khi có dòng thật. Nó không bao giờ có
`blind_test`.

## Hard case

`manifests/hard_cases.txt` gồm 47 mục: 13 từ theo dõi từ baseline, và những gì
VietOCR đọc sai trên 100 dòng bake-off:

- mất hoặc đổi dấu: `CỔNG`→`CÔNG`, `Nghị`→`Nghi`, `định`→`đinh`, `hội`→`hôi`;
- đổi hoa/thường: danh từ riêng bị viết thường, tiêu đề bị đổi kiểu chữ;
- dấu câu và ký hiệu bị rơi hoặc đọc sai: gạch đầu dòng, `;` cuối dòng, `./.`,
  dấu ngoặc kép, `+07:00`, `@`, `.vn`, `(ii)`.

Với mỗi mục, bộ sinh rút các dòng tự nhiên có chứa nó (12 dòng ở train, 2 ở
validation). Dòng thuộc loại này có `source_type=hard_case`.

Hard case **chỉ là mục tiêu train và đánh giá**. Không script nào dùng danh sách
này để thay thế hay "sửa" output của model.

Danh sách này là lý do chính khiến 100 dòng bake-off không còn là blind test.
Từ nay hard case mới chỉ được rút từ lỗi trên `real_val` hoặc
`bakeoff_regression`. **Không bao giờ từ `blind_test`.**

## Bộ pilot tổng hợp

```bash
python datasets/vietnamese_recognition/build_dataset.py     # sinh lại ảnh, khoảng 45 giây
python datasets/vietnamese_recognition/build_dataset.py --skip-synthetic   # chỉ cập nhật dòng thật và bản trộn
```

| | `synthetic_train` | `synthetic_val` |
| --- | --- | --- |
| Dòng thường | 3.000 | 300 |
| Dòng dài | 1.000 | 100 |
| Bù độ phủ chữ | 495 | 58 |
| Hard case | 564 | 94 |
| **Tổng** | **5.059** | **552** |

Seed: train `20261101`, validation `20261102`. Ảnh chiếm khoảng 150 MB và không
vào git; chúng được sinh lại từ seed. Vì kết quả phụ thuộc font và phiên bản
thư viện (ghi trong `manifests/build_report.json`), khi train trên máy khác nên
chép thư mục ảnh sang thay vì sinh lại ở đó.

Đây là bộ **pilot**, đủ nhỏ cho laptop. 5.000 dòng từ 6 họ font sẽ khiến model
thuộc font hơn là học đọc; `--scale` nhân mọi con số lên khi cần bộ lớn hơn.

## Audit và điều kiện sẵn sàng train

```bash
python datasets/vietnamese_recognition/audit_dataset.py
```

Báo cáo **riêng từng tập** (`real_train`, `real_val`, `synthetic_train`,
`synthetic_val`, `bakeoff_regression`; `blind_test` chỉ số dòng và số tài liệu):
số dòng, ký tự, từ; text duy nhất và trùng lặp; tài liệu nguồn và số dòng mỗi
tài liệu; phân bố `source_type` và font; độ phủ 178 chữ cái; phân bố độ dài nhãn
và tỉ lệ rộng/cao; ảnh hưởng của resize; tiến độ annotation.

Audit **FAIL** (mã thoát 1) khi:

- một tài liệu có dòng ở hai tập (train/val, train/blind, …), một tài liệu được
  đăng ký hai lần, một tài liệu benchmark được đăng ký như tài liệu mới, một
  tài liệu có dòng ở tập khác với tập nó được đăng ký, hoặc hai tài liệu ở hai
  tập khác nhau chung phần lớn text;
- cùng một ảnh hoặc cùng một id ở hai tập;
- một dòng đóng băng nằm trong tập khác, hoặc manifest của một tập đóng băng
  khác bản đóng băng;
- một dòng thật chưa được người verify nằm trong bất kỳ tập nào;
- một dòng `legacy_candidate` nằm trong bất kỳ tập nào;
- nhãn rỗng, không ở NFC, hoặc có ký tự ngoài vocab mà không được đánh dấu;
  nhãn dài hơn mức config hỗ trợ (hiện là 128 ký tự: `decoder_max_seq_length`
  128, `transformer.max_seq_length` 1024; audit in rõ giới hạn nào bị vượt);
  ảnh thiếu hoặc khác với hash đã ghi;
- một chữ cái tiếng Việt không xuất hiện trong train.

**Chỉ cảnh báo, không FAIL:** text giống nhau ở hai tập. Văn bản hành chính lặp
lại cùng những công thức (`Độc lập - Tự do - Hạnh phúc`, `Nơi nhận:`), và điều
đó tự nó không phải rò rỉ.

Tách khỏi PASS/FAIL, audit trả lời dataset đã đủ điều kiện để train chưa:

| Điều kiện | Cần | Hiện có |
| --- | --- | --- |
| Dòng `real_train` đã verify | ≥ 400 | 0 |
| Dòng `real_val` đã verify | ≥ 100 | 0 |
| Dòng `blind_test` đã verify | ≥ 100 | 0 |
| Tài liệu train | ≥ 6 | 0 |
| Tài liệu validation | ≥ 2 | 0 |
| Tài liệu blind | ≥ 2 | 0 |
| Rò rỉ tài liệu hoặc ảnh | 0 | 0 |

Thiếu một điều kiện là `TRAINING READY: NO`. Một dataset FAIL không bao giờ
được coi là sẵn sàng.

Kết quả hiện tại: **DATA AUDIT: PASS**, **TRAINING READY: NO**. Chưa có tài
liệu mới nào được đăng ký. 178/178 chữ cái có trong train (chữ hiếm nhất 30
lần); 0 id trùng, 0 ảnh ở hai tập, 0 rò rỉ tài liệu.

File trong `manifests/`: `dataset_audit.json`, `character_coverage.csv`
(số lần xuất hiện của từng chữ ở mỗi tập, không có cột blind),
`resize_report.csv`.

## Mục tiêu của model sau này

1. Đúng dấu tiếng Việt.
2. Chép đúng từng ký tự, kể cả hoa/thường và dấu câu.
3. Đọc được dòng hành chính dài.
4. Không bịa chữ ở đầu và cuối dòng.
5. Giữ nguyên chữ số và số hiệu văn bản.

Và không được chỉ thuộc lòng vài tài liệu: vì thế train, validation và blind
test đến từ những tài liệu khác nhau, và con số cuối cùng được đo trên tài liệu
chưa từng tham gia vào bất kỳ quyết định nào.

Config fine-tune và ước lượng tài nguyên: `configs/vietnamese/vietocr/README.md`.

## Test

```bash
python -m unittest discover -s datasets/vietnamese_recognition/tests
python -m unittest discover -s benchmarks/vietnamese/tests
```

# Dataset nhận dạng dòng chữ tiếng Việt

Dữ liệu để fine-tune recognizer VietOCR cho văn bản hành chính tiếng Việt, và
tập test đóng băng để đo kết quả.

Kiến trúc đã chốt sau bake-off: `PP-OCRv6_medium_det` → line crop dùng chung →
VietOCR. Thư mục này chỉ chuẩn bị dữ liệu. **Chưa có gì được train.**

```text
datasets/vietnamese_recognition/
├── test_holdout/     100 dòng test đóng băng (id, ground truth, hash của crop)
├── train/            ảnh train            (sinh ra, không vào git)
├── val/              ảnh validation       (sinh ra, không vào git)
├── manifests/        manifest, báo cáo    (sinh ra) và hard_cases.txt
├── real_annotation/  dòng thật chờ người verify (không vào git)
├── lexicon/          từ vựng hành chính cho bộ sinh câu
└── *.py, tests/
```

## Quy tắc số một: tập test đóng băng

100 dòng do người verify trong bake-off (4.853 ký tự, 1.053 từ, 3 tài liệu, 9
trang) là **tập test/holdout đóng băng**. Chúng không bao giờ được vào train hay
validation.

`test_holdout/test_holdout.tsv`:

```text
id  document  page  line_index  ground_truth  crop_sha256  split  frozen
```

Mọi dòng có `split=test`, `frozen=true`. File không chứa ảnh: `id` và
`crop_sha256` gắn ground truth với đúng một file crop trên máy đang giữ crop.

Tập test được bảo vệ ở năm chỗ:

| Ở đâu | Làm gì |
| --- | --- |
| `test_holdout.sha256` | Ghi SHA-256 của file lúc đóng băng. Mọi script đọc holdout đều kiểm tra, lệch là dừng. |
| `freeze_test_holdout.py` | Từ chối ghi holdout lần thứ hai. |
| `build_dataset.py` | Không ghi dòng nào có id, ảnh hoặc text của tập test vào train/val; vi phạm thì dừng. |
| `audit_dataset.py` | **FAIL** nếu train/val có id hoặc ảnh của tập test, hoặc `test.tsv` khác holdout. |
| `tests/test_holdout.py` | Ghim SHA-256 của holdout trong code; sửa ground truth là test hỏng. |

```bash
python datasets/vietnamese_recognition/freeze_test_holdout.py --check
```

Hai điều cần biết về tập test này:

- **Ground truth giữ nguyên như lúc verify.** 57 dòng được chấp nhận nguyên văn
  từ VietOCR; soi thử 12 dòng trong số đó thấy 5 dòng có vẻ không khớp hẳn với
  ảnh. Tập đã đóng băng nên không sửa; khi đọc kết quả sau này cần nhớ rằng nó
  hơi thiên về VietOCR gốc. Chi tiết: mục "Kết quả" trong
  `benchmarks/vietnamese/recognizer_bakeoff/README.md`.
- **Nó chỉ gồm 3 tài liệu.** Kết quả trên nó chưa nói được gì về tài liệu khác
  loại, khác font, khác chất lượng scan.

## Manifest chuẩn

Mỗi split một file TSV thuần (không quote, field không chứa tab) trong
`manifests/`: `train.tsv`, `val.tsv`, `test.tsv`.

| Cột | Ý nghĩa |
| --- | --- |
| `id` | Định danh duy nhất trong toàn bộ dataset |
| `source_document` | Tài liệu gốc; với dòng tổng hợp là `synthetic/<tên dataset>` |
| `page`, `line_index` | Vị trí trong tài liệu gốc; rỗng với dòng tổng hợp |
| `image_path` | Đường dẫn ảnh, tương đối so với thư mục này |
| `text` | Nhãn, UTF-8 NFC |
| `split` | `train`, `val` hoặc `test` |
| `source_type` | `real`, `synthetic` hoặc `hard_case` |
| `verified` | `true` khi nhãn chắc chắn đúng: dòng thật đã được người verify, hoặc dòng tổng hợp (nhãn chính là text đã vẽ) |
| `crop_sha256` | SHA-256 của file ảnh |
| `image_width`, `image_height` | Kích thước ảnh (pixel) |
| `subset` | `long_line`, `coverage` hoặc rỗng |
| `font` | Font đã vẽ (dòng tổng hợp) |
| `clean_image_path` | Ảnh sạch trước augmentation (dòng tổng hợp) |

Mười cột đầu là schema chuẩn; năm cột sau phục vụ phân tích dòng dài và audit.
`manifests/vietocr/*_annotation.txt` là cùng các split ở định dạng VietOCR đọc
(`đường dẫn ảnh<TAB>nhãn`).

## Dữ liệu thật

364 crop hiện có đều từ 3 tài liệu benchmark. 100 crop là tập test; 264 crop còn
lại **chưa có nhãn**.

- Prediction của OCR không bao giờ được dùng làm nhãn. Không có pseudo-label.
- Một dòng thật chỉ vào train sau khi người verify nó.

```bash
# Lập bảng các dòng có thể dùng làm dữ liệu train (chưa cần làm ngay)
python datasets/vietnamese_recognition/prepare_real_candidates.py

# Verify bằng công cụ đã dùng cho bake-off
python benchmarks/vietnamese/recognizer_bakeoff/annotate.py \
  --annotation-dir datasets/vietnamese_recognition/real_annotation --target 50

# Build lại: dòng đã verify được đưa vào train/val
python datasets/vietnamese_recognition/build_dataset.py
```

`prepare_real_candidates.py` loại 100 dòng test và thêm 5 crop là "bản sao
text" của một dòng test (cùng một con dấu hay tiêu đề lặp lại ở trang khác: train
trên chúng là học tập test bằng đường vòng). Còn lại **259 ứng viên**.

Khi chia dòng thật, cả một trang đi về cùng một split (cứ 5 trang thì 1 trang
vào validation), để các dòng liền nhau của một trang không nằm ở hai phía.

**Lưu ý quan trọng.** Cả 259 ứng viên đều nằm trên các trang đã có dòng trong
tập test. Train trên chúng thì tập test đo mức thuộc 3 tài liệu này, không còn
đo khả năng đọc tài liệu mới. Audit sẽ cảnh báo số dòng như vậy. Dữ liệu thật
đáng giá nhất là từ **tài liệu khác**.

## Dữ liệu tổng hợp

`text_generator.py` sinh dòng chữ theo phong cách văn bản hành chính từ từ vựng
trong `lexicon/administrative.txt`: tên cơ quan, tỉnh thành, tên luật, loại văn
bản, cụm động từ và danh từ quen dùng, chức danh, họ tên. Từ vựng là kiến thức
chung; không có câu nào lấy từ tài liệu benchmark, và không câu nào được lưu
sẵn nguyên vẹn.

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
  do cắt; VietOCR chỉ decode tối đa 128 token.
- **Không lặp text của tập test.** Mặc định bộ sinh bỏ qua mọi dòng trùng nguyên
  văn với một dòng test. Ba dòng mẫu quen thuộc (`QUYẾT ĐỊNH`, `QUYẾT ĐỊNH:`,
  `Độc lập - Tự do - Hạnh phúc`) nằm trong tập test nên không xuất hiện đứng
  riêng trong train; các từ đó vẫn có mặt trong những dòng khác. Muốn cho phép
  thì dùng `--allow-test-texts`.
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
| 100 dòng test thật | 4,5% | 9 / 100 |

Ảnh đã augment khó ngang crop thật, và model mắc đúng các kiểu lỗi đã thấy trên
dữ liệu thật: đổi hoa/thường ở dòng `Cơ quan: …`, bỏ `./.` ở cuối, thêm chữ ở
hai đầu dòng. Các dòng sai nặng nhất đều có ảnh đọc được.

## Dòng dài

VietOCR đưa ảnh về cao 32 px và rộng tối đa 512 px, nên mọi dòng có tỉ lệ
rộng/cao trên 16:1 bị nén ngang. Trong bake-off, 9 dòng VietOCR bịa chữ ở hai
đầu đều là dòng bị nén.

Bộ pilot có một tập con `long_line` gồm 1.000 dòng train và 100 dòng validation
dài từ 76 ký tự, tức dài hơn dòng VietOCR thường gặp. Manifest ghi chiều rộng,
chiều cao và số ký tự của từng dòng.

| | Train | Val | Test |
| --- | --- | --- | --- |
| Tỉ lệ tới 16:1 | 2.154 | 227 | 38 |
| 16:1 tới 24:1 | 1.573 | 177 | 21 |
| 24:1 tới 32:1 | 751 | 84 | 40 |
| Trên 32:1 | 581 | 64 | 1 |
| Nhãn từ 91 ký tự | 741 | 83 | 0 |
| Nhãn dài nhất | 119 | 118 | 81 |

**Resize làm gì với độ phân giải của ký tự.** Số pixel chiều ngang còn lại cho
mỗi ký tự sau khi VietOCR resize về cao 32 px, theo chiều rộng tối đa:

| Rộng tối đa | Test: dòng bị nén | Test: trung vị / phân vị 5 (px/ký tự) | Train: dòng bị nén | Train: trung vị / phân vị 5 |
| --- | --- | --- | --- | --- |
| 512 (pretrained) | 62 / 100 | 10,2 / 6,5 | 2.904 / 5.059 | 9,9 / 4,7 |
| 768 | 41 / 100 | 11,8 / 9,7 | 1.331 / 5.059 | 11,1 / 7,1 |
| **1024** | **1 / 100** | **12,7 / 11,0** | 580 / 5.059 | 11,4 / 8,6 |
| 1280 | 0 / 100 | 12,7 / 11,0 | 120 / 5.059 | 11,6 / 8,6 |

Ở 512 px, 5% số dòng test chỉ còn 6,5 px cho mỗi ký tự, khoảng một nửa mức của
dòng không bị nén; dấu thanh chồng dấu mũ khó sống sót ở mức đó. Ở 1024
px chỉ còn 1 dòng test bị nén. Vì vậy config fine-tune dùng rộng tối đa 1024.
Bộ train cố ý chứa cả dòng dài hơn mọi dòng test (11% trên 32:1), để model gặp
dòng dài trong lúc học chứ không phải lần đầu ở inference.

## Hard case

`manifests/hard_cases.txt` gồm 47 mục: 13 từ theo dõi từ baseline, và những gì
VietOCR đọc sai trên tập test đã verify:

- mất hoặc đổi dấu: `CỔNG`→`CÔNG`, `Nghị`→`Nghi`, `định`→`đinh`, `hội`→`hôi`;
- đổi hoa/thường: danh từ riêng bị viết thường, tiêu đề bị đổi kiểu chữ;
- dấu câu và ký hiệu bị rơi hoặc đọc sai: gạch đầu dòng, `;` cuối dòng, `./.`,
  dấu ngoặc kép, `+07:00`, `@`, `.vn`, `(ii)`.

Với mỗi mục, bộ sinh rút các dòng tự nhiên có chứa nó (12 dòng ở train, 2 ở
validation), tức mục đó xuất hiện trong ngữ cảnh thật của nó. Dòng thuộc loại
này có `source_type=hard_case`.

Hard case **chỉ là mục tiêu train và đánh giá**. Không script nào dùng danh sách
này để thay thế hay "sửa" output của model.

Một điều cần nhớ: một phần danh sách được rút ra từ chính lỗi trên tập test. Các
từ đó là từ vựng chung và được đặt vào câu mới, nhưng tập test vì thế không còn
hoàn toàn "chưa từng được nhìn" khi thiết kế dữ liệu train. Kết luận cuối cùng
về model đã fine-tune nên dựa thêm vào tài liệu chưa dùng tới.

## Bộ pilot hiện tại

```bash
python datasets/vietnamese_recognition/build_dataset.py     # khoảng 45 giây
python datasets/vietnamese_recognition/audit_dataset.py
```

| | Train | Validation | Test |
| --- | --- | --- | --- |
| Dòng thật đã verify | 0 | 0 | 100 |
| Tổng hợp, dòng thường | 3.000 | 300 | – |
| Tổng hợp, dòng dài | 1.000 | 100 | – |
| Tổng hợp, bù độ phủ chữ | 495 | 58 | – |
| Hard case | 564 | 94 | – |
| **Tổng** | **5.059** | **552** | **100** |

Seed: train `20261101`, validation `20261102`. Ảnh chiếm khoảng 150 MB và không
vào git; chúng được sinh lại từ seed. Vì kết quả phụ thuộc font và phiên bản
thư viện (ghi trong `manifests/build_report.json`), khi train trên máy khác nên
chép thư mục ảnh sang thay vì sinh lại ở đó.

Đây là bộ **pilot** để kiểm tra toàn bộ đường ống, đủ nhỏ cho laptop. Nó chưa
đủ lớn để fine-tune cho ra model tốt: 5.000 dòng từ 6 họ font sẽ khiến model
thuộc font hơn là học đọc. `--scale` nhân mọi con số lên khi cần bộ lớn hơn.

## Audit

`audit_dataset.py` báo cáo: số mẫu mỗi split, text duy nhất và trùng lặp, hash
ảnh trùng, giao giữa các split, độ phủ và số lần xuất hiện của từng chữ cái
tiếng Việt, phân bố dòng dài, ảnh hưởng của resize, phân bố `source_type`.

Audit **FAIL** (mã thoát 1) khi:

- một dòng test đóng băng nằm trong train/val, theo id hoặc theo ảnh;
- `test.tsv` không đúng bằng holdout;
- trùng id, hoặc một dòng nằm sai file split;
- nhãn rỗng, không ở NFC, dài hơn giới hạn decode, hoặc có ký tự ngoài vocab;
- một dòng thật chưa được người verify nằm trong train/val;
- ảnh thiếu hoặc khác với hash đã ghi;
- một chữ cái tiếng Việt không xuất hiện trong train.

Những điều sau chỉ là cảnh báo để người xem xét: text trùng lặp, text trùng với
một dòng test, dòng thật trong train nằm cùng trang với dòng test.

Kết quả trên bộ pilot: **PASS**. 0 id trùng, 0 ảnh trùng, 0 giao với tập test
(id, ảnh và text), 178/178 chữ cái có trong train, chữ hiếm nhất 30 lần, 88 chữ
PP-OCRv6 thiếu xuất hiện tổng cộng 28.202 lần.

File trong `manifests/`: `dataset_audit.json`, `character_coverage.csv`
(số lần xuất hiện của từng chữ ở mỗi split), `resize_report.csv`.

## Mục tiêu của model sau này

1. Đúng dấu tiếng Việt.
2. Chép đúng từng ký tự, kể cả hoa/thường và dấu câu.
3. Đọc được dòng hành chính dài.
4. Không bịa chữ ở đầu và cuối dòng.
5. Giữ nguyên chữ số và số hiệu văn bản.

Và không được chỉ thuộc lòng 3 tài liệu benchmark: vì thế dữ liệu tổng hợp không
lấy gì từ chúng, và tập test tách khỏi mọi thứ dùng để train.

Config fine-tune và ước lượng tài nguyên: `configs/vietnamese/vietocr/README.md`.

## Test

```bash
python -m unittest discover -s datasets/vietnamese_recognition/tests
python -m unittest discover -s benchmarks/vietnamese/tests
```

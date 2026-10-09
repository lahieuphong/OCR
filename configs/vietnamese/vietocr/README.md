# Config fine-tune VietOCR: thí nghiệm chiều rộng ảnh

Ba file, để fine-tune VietOCR trên dataset trong
`datasets/vietnamese_recognition/`. **Chưa có gì được train bằng chúng.**

| File | Nội dung |
| --- | --- |
| `exp_a_width512.yml` | Experiment A: `image_max_width = 512` (giá trị pretrained) |
| `exp_b_width1024.yml` | Experiment B: `image_max_width = 1024` |
| `data_mix.yml` | Cách trộn dòng thật và dòng tổng hợp trong một lượt train |

Hai file `exp_*.yml` được sinh ra, không sửa bằng tay:

```bash
python datasets/vietnamese_recognition/build_vietocr_config.py            # ghi lại
python datasets/vietnamese_recognition/build_vietocr_config.py --check    # kiểm tra
```

Mỗi file là config `vgg_transformer` của bản VietOCR đã pin
(`third_party/vietocr`, commit `fe8c3a7fc714aec57ab81cec844eb3adf0c1636c`:
`config/base.yml` gộp với `config/vgg-transformer.yml`), cộng các thay đổi liệt
kê trong `OVERRIDES` của script. Không file nào trong `third_party/vietocr` bị
sửa.

## Chưa chọn width

Số liệu resize gợi ý rằng 1024 px có lợi cho dòng dài: ở 512 px, 62 trong 100
dòng bake-off bị nén ngang và 5% số dòng chỉ còn 6,5 px cho mỗi ký tự. Nhưng
model pretrained chưa từng thấy ảnh rộng hơn 512 px, và khi thử cho nó đọc ở
1024 px mà không fine-tune thì nó dừng giữa dòng. Fine-tune có dạy được nó hay
không thì chưa ai đo. Vì vậy **1024 chưa được chọn**: hai experiment sẽ trả lời.

Hai config **giống hệt nhau** trừ chiều rộng và nơi ghi kết quả. Test
`tests/test_vietocr_config.py` so từng khoá và chỉ cho phép sáu khoá khác nhau:
`dataset.image_max_width`, `weights`, `trainer.export`, `trainer.checkpoint`,
`trainer.log`, `experiment.name`.

| Giống nhau ở cả hai | Giá trị |
| --- | --- |
| Dữ liệu train | `manifests/vietocr/train_mix_annotation.txt` (thật + tổng hợp theo `data_mix.yml`) |
| Dữ liệu validation | `manifests/vietocr/real_val_annotation.txt` (toàn dòng thật) |
| Seed | `20261201` |
| Checkpoint pretrained | `models/vietocr/vgg_transformer.pth` |
| Learning rate (đỉnh) | 0,0001, OneCycleLR, `pct_start` 0,1 |
| Batch size | 16 |
| Số bước gradient | 9.500 vòng lặp, validation mỗi 320 vòng |
| Augmentation của VietOCR | tắt |
| `decoder_max_seq_length` | 128 (khoá của project, VietOCR không đọc) |

Cùng batch size và cùng số vòng lặp nghĩa là hai experiment thực hiện cùng số
bước gradient trên cùng số mẫu. Nếu batch 16 không vừa bộ nhớ ở 1024 px thì giảm
batch cho **cả hai** config (trong `OVERRIDES`), không giảm riêng một bên.

## Chọn theo gì

- **CER trên `real_val`** (hoà thì theo WER). Áp dụng cho việc chọn checkpoint
  trong một lần train và cho việc chọn giữa A và B.
- `synthetic_val` và `bakeoff_regression` được báo kèm để chẩn đoán, không dùng
  để chọn.
- **`blind_test` không tham gia.** Nó chỉ được chấm một lần, sau khi đã chọn
  xong, bằng `evaluate_splits.py score --unlock-blind-test`.

Các điều này được ghi trong khối `experiment` của mỗi config (`selection_split`,
`selection_metric`, `selection_tiebreak`, `diagnostic_splits`,
`blind_test_used_for_selection: false`). VietOCR không đọc khối đó; nó là hợp
đồng cho script train sẽ viết ở phase sau.

**Hai việc chưa làm, phải làm trước khi chạy experiment:**

1. `vietocr.model.trainer.Trainer` giữ weights tốt nhất theo *tỉ lệ dòng đúng
   hoàn toàn* trên file validation, không theo CER. File validation đã là
   `real_val`, nên tiêu chí của nó cũng dựa trên dòng thật, nhưng chưa đúng
   metric đã thống nhất. Cần một script train bọc ngoài, tính CER trên `real_val`
   ở mỗi lần validation và giữ checkpoint tốt nhất theo đó.
2. Trainer của VietOCR không đặt seed. Script bọc ngoài phải đặt seed
   (`experiment.seed`) cho Python, NumPy và PyTorch trước khi dựng model, nếu
   không hai experiment không cùng điều kiện.

Phase này cố ý không viết script train nào.

## Giá trị so với pretrained

| Mục | Giá trị | Pretrained | Ghi chú |
| --- | --- | --- | --- |
| Model gốc | `vgg_transformer` (VGG19-bn + Transformer) | như vậy | 37.650.217 tham số |
| Checkpoint pretrained | `models/vietocr/vgg_transformer.pth` | URL `vocr.vn` | cùng file bake-off đã đánh giá, SHA-256 `38051219…75ea59` |
| Vocab | 229 ký tự, **không đổi** | như vậy | đã đủ 178 chữ cái tiếng Việt |
| Chiều cao ảnh | 32 | 32 | |
| Chiều rộng tối đa | 512 (A) / 1024 (B) | 512 | |
| Batch size | 16 | 32 | xem "Bộ nhớ" |
| Learning rate (đỉnh) | **0,0001** | 0,0003 | |
| Số vòng lặp | 9.500 | 100.000 | **tính lại khi có dòng thật**, xem dưới |
| Thiết bị | `cuda:0` | `cuda:0` | |
| Augmentation của VietOCR | **tắt** | bật | |
| Masked language model | bật | bật | |
| Kết quả | `models/vietocr/finetuned/<tên experiment>/` | | `weights.pth`, `checkpoint.pth`, `train.log`; ngoài git |

**Số vòng lặp.** VietOCR đếm theo vòng lặp chứ không theo epoch:
`iters = số lượt × ⌈số mẫu mỗi lượt / batch size⌉`. Con số 9.500 là khoảng 30
lượt trên 5.059 dòng tổng hợp. Khi có 400 dòng thật, một lượt theo `data_mix.yml`
là 7.459 mẫu, tức 467 vòng; 30 lượt là khoảng 14.000 vòng và `valid_every` nên
là 467. Hai giá trị này phải được tính lại **một lần, cho cả hai config**, khi
`real_train` đã chốt.

**Vì sao giữ nguyên vocab.** Vocab của model pretrained đã có mọi chữ cái tiếng
Việt, kể cả 88 chữ PP-OCRv6 thiếu. Đổi vocab là đổi kích thước lớp output, và
lớp đó sẽ không nạp được từ checkpoint nữa. Cái giá: model không thể xuất ký tự
ngoài 229 ký tự này (ví dụ gạch dài `–`, ngoặc kép cong, `…`). Dòng thật có ký
tự như vậy được giữ nguyên nhãn, đánh dấu `out_of_vocabulary` và để ngoài file
train/validation. Vocab không được chỉnh theo những gì thấy trong `blind_test`.

**Vì sao learning rate thấp hơn.** Mục đích là điều chỉnh một model đã đọc tốt,
không phải dạy lại từ đầu trên vài nghìn dòng.

**Vì sao tắt augmentation của VietOCR.** Ảnh tổng hợp đã được làm giống văn bản
scan, theo cách tái lập được từ seed, và ảnh thật thì đã là ảnh scan. Phép biến
đổi có sẵn của VietOCR còn đảo màu 20% số ảnh và vẽ các đường kẻ màu ngẫu nhiên,
những thứ không có trên văn bản hành chính.

## Giới hạn decode: `decoder_max_seq_length`

VietOCR không có giới hạn độ dài nhãn nào trong kiến trúc ngoài 1024 vị trí của
transformer: `Vocab.encode` và collator nhận nhãn dài bất kỳ. Giới hạn thực tế
nằm ở lúc đọc: `translate()` dừng sau `max_seq_length` bước, mặc định 128, và
`Predictor.predict` không bao giờ truyền số nào khác.

Runner của project (`run_vietocr.py`) vì vậy tự gọi `translate()` và luôn truyền
con số đó. Không có gì trong `third_party/vietocr` bị sửa hay patch.

| Cách chạy | Số bước decode |
| --- | --- |
| không có `--config` (chạy lại bake-off) | 128, mặc định của VietOCR, để prediction gốc tái lập được |
| `--config exp_*.yml` | `decoder_max_seq_length` của config: **128** |
| `--decoder-max-seq-length N` | N (chỉ để chẩn đoán, phải có `--output` riêng) |

Với N bước, decoder viết tối đa N + 1 token, nên một dòng N ký tự còn chỗ cho
token kết thúc. Nhãn dùng được dài tối đa
`min(decoder_max_seq_length, transformer.max_seq_length − 2)` = **128 ký tự**;
audit lấy con số này từ file config, không còn hằng số 126. Một nhãn dài hơn
làm audit FAIL và nêu rõ giới hạn nào bị vượt.

Giá trị trong config trùng với mặc định của VietOCR, nhưng nó là một cấu hình
được ghi ra và truyền đi, không phải thứ ngầm định: đổi một dòng trong
`OVERRIDES` của `build_vietocr_config.py` rồi sinh lại config là runner, audit
và bước kiểm config cùng theo.

Mỗi prediction ghi `hit_decoder_limit`: decoder hết bước mà chưa viết token kết
thúc. Text như vậy có thể bị cắt, hoặc là model viết mãi không dừng.

**Vì sao 128 chứ không phải 160.** So sánh hai mức trên model pretrained (chỉ
inference, 100 dòng `bakeoff_regression` và 100 dòng `real_val` đã verify lúc
đo; không đụng `blind_test`):

| Tập | Bước | CER | WER | Dòng đúng hoàn toàn | Hết bước |
| --- | --- | --- | --- | --- | --- |
| `bakeoff_regression` | 128 | 4,51% | 8,83% | 57% | 0 |
| `bakeoff_regression` | 160 | 4,51% | 8,83% | 57% | 0 |
| `real_val` | 128 | 4,54% | 11,21% | 55% | 1 |
| `real_val` | 160 | 5,22% | 11,31% | 54% | 1 |

199 trên 200 prediction giống hệt nhau; lần chạy 128 bước trùng 100/100 với
prediction đã lưu của bake-off. Dòng duy nhất khác là một dòng chấm dẫn có chữ
viết tay, crop rộng 85 px: model viết dấu chấm mãi không dừng ở cả hai mức (129
ký tự ở 128 bước, 161 ký tự ở 160 bước). Nhãn 129 ký tự của dòng đó chính là
output bị chặn ở 128 bước đã được chấp nhận làm ground truth, nên 160 bước bị
tính thêm 32 lỗi. Bỏ dòng đó ra, hai mức cho đúng cùng một kết quả (CER 4,67%,
WER 11,22% trên 99 dòng).

Vì vậy config dùng **128**:

- Không nhãn thật nào đã verify cần hơn 128 bước (dài nhất 92 ký tự), và nhãn
  tổng hợp dài nhất là 119.
- Trên các dòng model tự kết thúc, 128 và 160 không khác nhau. Khác biệt chỉ
  xuất hiện khi model không dừng, và khi đó giới hạn dài hơn chỉ cho thêm ký tự
  thừa.
- Một prediction có `hit_decoder_limit` không được chấp nhận làm ground truth
  mà không đếm lại trên ảnh. Nhãn 129 ký tự nói trên là một ground truth sai
  theo đúng cách đó.

Khi có nhãn thật dài hơn 128 ký tự thì nâng giá trị này lên, cho cả hai config.

**Việc của Phase 4.** `Trainer` của VietOCR tự chấm validation bằng `translate()`
mặc định 128 bước. Script train bọc ngoài phải chấm `real_val` bằng runner của
project, với số bước lấy từ config.

## Trộn dữ liệu: `data_mix.yml`

```yaml
real_to_synthetic: [1, 2]
method: oversample_real        # hoặc subsample_synthetic
max_real_repeats: 10
seed: 20261201
```

`build_dataset.py` đọc file này và ghi `train_mix_annotation.txt`. Tỉ lệ khởi
đầu là 1 thật : 2 tổng hợp, đạt bằng cách lặp dòng thật. Đây là điểm xuất phát,
không phải kết luận: đổi giá trị rồi chạy `build_dataset.py --skip-synthetic`.
Nếu tỉ lệ trộn trở thành thứ cần so sánh thì nó cũng được chọn trên `real_val`.

## Kiểm tra trước khi train

```bash
.venv-vietocr/bin/python datasets/vietnamese_recognition/check_vietocr_config.py
```

Với mỗi config, script làm những việc một lần train sẽ làm trước bước đầu tiên
rồi dừng: dựng model, nạp checkpoint, mã hoá mọi nhãn, kiểm tra file train và
validation không chứa dòng nào của `blind_test` hay `bakeoff_regression` và
validation là toàn dòng thật, rồi chạy một lượt forward không gradient. Không
optimizer nào được tạo, không trọng số nào thay đổi.

Kết quả hiện tại, giống nhau ở cả hai config:

- 0 tensor pretrained bị thiếu, 0 tensor lệch shape;
- 5.059 nhãn train đều mã hoá được, ảnh đều có mặt, nhãn dài nhất 119 ký tự
  (config hỗ trợ tới 128);
- forward ở rộng 512 và 1024 đều chạy, output `(1, 100, 233)`;
- **`READY TO TRAIN FROM: NO`**: `real_val_annotation.txt` chưa có dòng nào.

Nghĩa là hai config đúng về cấu trúc, nhưng chưa train được cho tới khi có
`real_val`. Điều kiện đầy đủ nằm ở `audit_dataset.py` (`TRAINING READY`).

## Bộ nhớ và thời gian

Đo một lượt forward của một ảnh, trên CPU của máy này:

| Rộng | Activations | Thời gian |
| --- | --- | --- |
| 512 | 116 MB | khoảng 0,1 s |
| 1024 | 217 MB | khoảng 0,13 s |

Từ đó **ngoại suy** cho một bước train (activations giữ lại cho backward cộng
gradient của chúng, và 4 bản tham số cho AdamW). Đây là ước lượng, không phải số
đo của việc train:

| Rộng | Batch | Bộ nhớ ước tính |
| --- | --- | --- |
| 512 | 16 | 4,2 GB |
| 1024 | 4 | 2,3 GB |
| 1024 | 16 | 7,4 GB |

Batch 16 ở 1024 px vừa một GPU 12 GB. VietOCR gom các ảnh cùng chiều rộng vào
một batch, nên chỉ những batch dòng dài mới chạm mức này. Experiment B tốn
khoảng gấp đôi A cho các batch đó.

Môi trường `.venv-vietocr` hiện chỉ đủ cho inference. Train cần thêm các thư
viện mà `vietocr.model.trainer` import: `lmdb`, `albumentations`, `matplotlib`,
`prefetch_generator`, `six` và OpenCV. Chúng **chưa được cài**. Mac M2 8 GB đủ
cho một smoke test vài chục bước, không đủ cho train thật.

## Khi train (chưa làm)

Vài điều nên biết trước:

- VietOCR tạo cache LMDB `train_vi_admin_pilot_v1/` và `valid_vi_admin_pilot_v1/`
  ngay trong thư mục đang đứng. Cache lưu ảnh gốc và resize lúc nạp, nên hai
  experiment dùng chung được. Đổi dataset hoặc tỉ lệ trộn mà không xoá cache là
  train trên dữ liệu cũ.
- Thứ tự chạy: A và B với cùng seed; chấm cả hai trên `real_val`,
  `synthetic_val`, `bakeoff_regression` bằng `evaluate_splits.py`; chọn; rồi mới
  mở khoá `blind_test` cho config đã chọn, một lần.
- Bộ tổng hợp pilot (5.059 dòng, 6 họ font) nhỏ. Trước khi train thật nên cân
  nhắc sinh bộ lớn hơn (`build_dataset.py --scale`).

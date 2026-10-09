# Config fine-tune VietOCR: thí nghiệm chiều rộng ảnh

Ba file, để fine-tune VietOCR trên dataset trong
`datasets/vietnamese_recognition/`. **Mới chỉ chạy smoke train 20 bước cho mỗi
config; chưa có lần train đầy đủ nào.**

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
| Batch size | 16 dòng mỗi lượt forward, không tích luỹ gradient (batch hiệu dụng 16) |
| Số bước optimizer | 4.670 (khoảng 10 lượt qua 7.459 mẫu), validation mỗi 233 bước |
| Augmentation của VietOCR | tắt |
| Thống kê BatchNorm | **đóng băng** theo checkpoint pretrained (`experiment.batch_norm_statistics: frozen`) |
| `decoder_max_seq_length` | 128 (khoá của project, VietOCR không đọc) |

Cùng batch size và cùng số bước nghĩa là hai experiment thực hiện cùng số bước
optimizer trên cùng số mẫu. Nếu batch 16 không vừa bộ nhớ ở 1024 px thì giảm
batch cho **cả hai** experiment, không giảm riêng một bên; lý do nằm ở mục
"Batch normalization" bên dưới.

## Chọn theo gì

- **CER trên `real_val`** (hoà thì theo WER). Áp dụng cho việc chọn checkpoint
  trong một lần train và cho việc chọn giữa A và B.
- `synthetic_val` và `bakeoff_regression` được báo kèm để chẩn đoán, không dùng
  để chọn.
- **`blind_test` không tham gia.** Nó chỉ được chấm một lần, sau khi đã chọn
  xong, bằng `evaluate_splits.py score --unlock-blind-test`.

Các điều này được ghi trong khối `experiment` của mỗi config (`selection_split`,
`selection_metric`, `selection_tiebreak`, `diagnostic_splits`,
`blind_test_used_for_selection: false`). VietOCR không đọc khối đó;
`train_vietocr.py` thì đọc.

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
| Số bước optimizer | 4.670 | 100.000 | tính từ lượt train đã chốt, xem dưới |
| Thiết bị | `cuda:0` | `cuda:0` | |
| Augmentation của VietOCR | **tắt** | bật | |
| Masked language model | bật | bật | |
| Kết quả | `models/vietocr/finetuned/<tên experiment>/` | | `weights.pth`, `checkpoint.pth`, `train.log`; ngoài git |

**Lịch train.** Không còn là hằng số: `build_vietocr_config.py` tính từ số mẫu
của một lượt train mà `build_dataset.py` ghi trong `manifests/build_report.json`.

| | |
| --- | --- |
| Mẫu mỗi lượt | 7.459 (400 dòng thật × 6 + 5.059 dòng tổng hợp) |
| Batch hiệu dụng | 16 |
| Bước mỗi epoch | ⌈7.459 / 16⌉ = 467 |
| Số epoch | 10 |
| Tổng số bước | 4.670 |
| Validation | mỗi 233 bước (hai lần mỗi epoch), và ở bước 0 và bước cuối |
| Learning rate | OneCycleLR: 4e-6 → đỉnh 1e-4 sau 467 bước → về gần 0 |

10 epoch là mức khởi đầu thận trọng: mỗi dòng thật đã được lặp 6 lần trong một
lượt, và weights được giữ là weights tốt nhất trên `real_val`, không phải weights
cuối. Nếu điểm tốt nhất rơi vào những lần validation cuối cùng thì đó là dấu hiệu
nên chạy thêm, không phải nên dừng.

"Epoch" ở đây là danh nghĩa. Như trainer gốc, mỗi lượt chỉ ghép các dòng cùng
chiều rộng vào một batch và bỏ ra batch không đủ, nên với batch 16 một lượt cho
443 batch ở 512 px (371 mẫu ngoài lượt) và 421 batch ở 1024 px (723 mẫu ngoài
lượt); mẫu bị bỏ ra thay đổi theo từng lượt. Hai experiment vẫn có đúng cùng số
bước và cùng số mẫu đã xem. 41 mẫu thuộc ba chiều rộng có dưới 16 dòng không bao
giờ ghép đủ một batch 16, ở cả hai experiment.

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

`Trainer` của VietOCR tự chấm validation bằng `translate()` mặc định. Script
train của project (`train_vietocr.py`) chấm `real_val` bằng chính hàm của runner,
với số bước lấy từ config, nên con số nó ghi lúc train là con số
`evaluate_splits.py` sẽ cho với cùng weights.

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

## Script train: `train_vietocr.py`

```bash
.venv-vietocr/bin/python datasets/vietnamese_recognition/train_vietocr.py \
  --config configs/vietnamese/vietocr/exp_a_width512.yml
```

Script này không gọi `vietocr.model.trainer.Trainer`. Trainer gốc giữ weights
theo tỉ lệ dòng đúng hoàn toàn, chấm validation với 128 bước decode bất kể
config, không đặt seed, không tích luỹ gradient, không lưu trạng thái scheduler,
và phải có LMDB, albumentations, matplotlib mới import được. Không điều nào sửa
được mà không đụng vào `third_party/vietocr`, nên checkout được giữ nguyên.

| | |
| --- | --- |
| Của VietOCR, gọi nguyên như vậy | mạng (`build_model`), vocab, tiền xử lý ảnh (`process_image`, `resize`), loss (`LabelSmoothingLoss`), decode (`translate`) |
| Làm lại theo trainer gốc | AdamW(betas 0,9/0,98, eps 1e-9), OneCycleLR, một bước (forward, loss smoothing 0,1, clip norm 1, optimizer, scheduler), batch theo chiều rộng, collate và che 5% token |
| Thêm vào | seed, chọn weights theo CER rồi WER trên `real_val`, tích luỹ gradient, lưu đủ trạng thái để resume |
| Khác trainer gốc, có chủ ý | thống kê BatchNorm đóng băng (trainer gốc cập nhật chúng); xem "Batch normalization" |

Các phần "làm lại" đều có test so với code gốc: collate và mask cho đúng kết quả
của `Collator`; một bước không tích luỹ cho đúng weights của `Trainer.step`; một
lần chạy được khôi phục từ checkpoint tiếp tục giống hệt lần chạy liền mạch.

Mỗi lần validation (bước 0, mỗi 233 bước, bước cuối):

- đọc 100 dòng `real_val`: **đây là thứ duy nhất quyết định weights nào được giữ**
  (CER thấp nhất, hoà thì WER thấp nhất);
- đọc `synthetic_val` để chẩn đoán, không chọn gì;
- không mở `blind_test`, không mở `bakeoff_regression`.

Weights pretrained là ứng viên đầu tiên (bước 0). Nếu không bước nào tốt hơn nó
trên `real_val` thì `weights.pth` vẫn là weights pretrained.

File ghi ra trong `models/vietocr/finetuned/<experiment>/` (ngoài git):

| File | Nội dung |
| --- | --- |
| `weights.pth` | weights có CER `real_val` tốt nhất |
| `last.pth` | weights ở lần validation gần nhất |
| `checkpoint.pth` | toàn bộ trạng thái: weights, optimizer, scheduler, random state, lịch sử |
| `report.json` | cấu hình, digest của input, mọi lần validation, lựa chọn |
| `train.log` | |

Script dừng trước khi tính gradient nếu: input khác bản ghi digest; experiment
kia đã chạy trên dữ liệu khác hoặc với cấu hình khác (batch, tích luỹ, mixed
precision, batch-norm); file train hay validation chứa dòng không thuộc bốn tập
train/validation; có nhãn ngoài vocab hoặc dài quá giới hạn; checkpoint
pretrained không nạp đủ; ổ đĩa còn dưới 1,5 GB.

Script chỉ mở manifest của bốn tập `real_train`, `synthetic_train`, `real_val`,
`synthetic_val`. Manifest của `blind_test` và `bakeoff_regression` không bao giờ
được mở trong lúc train; `report.json` ghi lại danh sách manifest đã mở.

## Digest của input: `training_inputs.py`

```bash
python datasets/vietnamese_recognition/training_inputs.py --check
```

`manifests/training_inputs.json` ghi SHA-256 của bốn manifest, hai file
annotation mà lần train đọc, hai config, `data_mix.yml` và checkpoint
pretrained. Mọi `report.json` chép lại các digest này. Nếu dữ liệu của A và B
khác nhau, lần chạy sau dừng lại.

| Input | SHA-256 |
| --- | --- |
| `real_train.tsv` | `7e0265b2e165f65e3447dda08b4ad25251ddca84d09b8da2f4f52ac762708d36` |
| `real_val.tsv` | `a7059843a33208aca0c1100176c1c020f73d76a07d01649e6a83216b1fb5e6a6` |
| `synthetic_train.tsv` | `03d177e20271edbf83456434df52c60a86ad33cb04a866c350537a238e5741cb` |
| `synthetic_val.tsv` | `06dca6aac0e1b933900201893c1cddacddd74e869cc8b8a85f26e547e408f791` |
| `train_mix_annotation.txt` | `9511e514a7eec3cc6b9860c222aad2a76069c1043eb84eb2f68a1fbf5f2ef682` |
| `real_val_annotation.txt` | `864c6110e01e0722db6450cd9faf03f482a81b82ee5934699a84d2179f04d0b8` |
| checkpoint pretrained | `380512193a8b6cbf6fad80deacdc9b6939d10d473d199892fc6408d13775ea59` |

Digest của hai config nằm trong file JSON; chúng đổi mỗi khi config được sinh lại
với giá trị khác, và khi đó phải ghi lại bằng `--force`.

## Baseline pretrained

Cùng checkpoint pretrained, đọc với từng config, 128 bước decode, trên CPU. Đây
là mốc để so mọi checkpoint của Phase 4. `blind_test` không được chấm.

| Width | Tập | CER | WER | Dòng đúng hoàn toàn | Hết bước decode |
| --- | --- | --- | --- | --- | --- |
| 512 | `real_val` | 4,48% | 10,64% | 56,0% | 0 |
| 512 | `synthetic_val` | 4,48% | 10,47% | 48,9% | 5 |
| 512 | `bakeoff_regression` | 4,51% | 8,83% | 57,0% | 0 |
| 1024 | `real_val` | 30,64% | 39,65% | 30,0% | 0 |
| 1024 | `synthetic_val` | 26,97% | 33,72% | 26,8% | 0 |
| 1024 | `bakeoff_regression` | 31,98% | 39,13% | 25,0% | 0 |

Model pretrained chưa từng thấy ảnh rộng hơn 512 px, nên ở 1024 px nó đọc kém
hơn nhiều. Vì vậy experiment B xuất phát từ mức thấp hơn hẳn A: câu hỏi của thí
nghiệm là sau fine-tune B có vượt được A trên `real_val` hay không, không phải B
cải thiện được bao nhiêu so với chính nó.

Số liệu đầy đủ: `manifests/evaluations/phase4_pretrained_w512.json` và
`phase4_pretrained_w1024.json`.

## Batch normalization: thống kê đóng băng

Backbone là VGG19 có 16 lớp batch-norm. Ở chế độ train, như trainer gốc chạy,
các lớp này chuẩn hoá bằng thống kê của các dòng trong lượt forward hiện tại và
ghi đè thống kê đã lưu bằng trung bình trượt của chúng. Cả hai đều phụ thuộc
**số dòng mỗi lượt forward**, và tích luỹ gradient không thay đổi điều đó: bốn
lượt 4 dòng không phải là một lượt 16 dòng đối với batch-norm.

Smoke đầu tiên của A, chạy theo cách của trainer gốc, cho thấy cái giá: sau 20
bước ở learning rate 4e-6, weights dịch 0,03% còn thống kê batch-norm dịch 34%,
và trên `real_val` tỉ lệ dòng đúng hoàn toàn rơi từ 56% xuống 32%. Đặt lại thống
kê pretrained cho chính weights đó thì được 58%; weights pretrained với thống kê
mới chỉ còn 29%.

**Chính sách của cả hai experiment: `experiment.batch_norm_statistics: frozen`.**
Chính xác thì:

- trong lúc train, mọi lớp batch-norm ở chế độ evaluation: chúng chuẩn hoá bằng
  `running_mean` và `running_var` của checkpoint pretrained, không bao giờ bằng
  thống kê của batch hiện tại;
- `running_mean`, `running_var` và bộ đếm `num_batches_tracked` không đổi;
- `gamma` và `beta` (weight, bias) của các lớp đó vẫn là tham số: nhận gradient
  và được optimizer cập nhật;
- không gì khác bị đóng băng: mọi lớp tích chập của backbone và toàn bộ
  transformer đều được train, dropout vẫn bật.

Mỗi điểm trên có test (`tests/test_training.py`), và smoke kiểm tra lại trên mô
hình thật: 0 trên 48 tensor thống kê thay đổi, 32 trên 32 tensor gamma/beta đã
được cập nhật.

Hai hệ quả:

- Đầu ra của một dòng không còn phụ thuộc các dòng khác trong batch, nên batch
  nhỏ kèm tích luỹ gần với batch 16 hơn nhiều so với trước. Dù vậy A và B vẫn
  phải dùng **cùng `trainer.batch_size`**; script từ chối chạy nếu khác.
- Đây là điểm duy nhất script cố ý làm khác trainer gốc. Đổi lại thành `updated`
  là sửa một dòng trong `OVERRIDES` rồi sinh lại config và ghi lại digest.

## Smoke train

20 bước optimizer đầu tiên của lịch thật, trên CPU của máy M2, batch 4 × tích
luỹ 4. Smoke chứng minh đường ống chạy được; **các con số của nó không phải kết
quả train**, kể cả con số tốt.

| | A (512), thống kê đóng băng | A (512), kiểu trainer gốc | B (1024), kiểu trainer gốc |
| --- | --- | --- | --- |
| Kết quả | PASS | PASS | PASS |
| `real_val` ở bước 0 | đúng bằng baseline 512 | đúng bằng baseline 512 | đúng bằng baseline 1024 |
| Loss (hữu hạn) | 0,72 → 0,76 | 1,48 → 1,33 | 1,47 → 1,30 |
| `real_val` sau 20 bước (CER / dòng đúng) | 1,62% / 70% | 4,55% / 32% | 32,08% / 14% |
| Tensor nhận gradient | 253 / 253 | 253 / 253 | 253 / 253 |
| Thống kê BatchNorm | 0 / 48 tensor đổi | bị ghi đè | bị ghi đè |
| Gamma, beta của BatchNorm | 32 / 32 được cập nhật | được cập nhật | được cập nhật |
| Checkpoint nạp lại | weights, optimizer, scheduler khớp | khớp | khớp |
| `weights.pth` nạp lại | cho đúng CER đã ghi | đúng | đúng |
| Nhãn ngoài vocab trong train | 0 | 0 | 0 |
| Dòng ngoài bốn tập train/validation | 0 | 0 | 0 |
| RAM đỉnh của tiến trình | 1,3 GB | 1,5 GB | 1,7 GB |

Với thống kê đóng băng, loss bắt đầu ở mức của một model đang đọc đúng (0,7 thay
vì 1,5), và 20 bước ở learning rate rất nhỏ đã kéo CER `real_val` từ 4,48% xuống
1,62%. Đó là một dấu hiệu tốt cho chính sách này, không phải một kết quả: mới 20
bước, chưa chấm `bakeoff_regression`, và smoke của B với thống kê đóng băng chưa
được chạy trên máy này. Hai smoke kiểu trainer gốc được giữ lại trong
`smoke_updated_statistics/` để đối chiếu.

**Resume.** Test đơn vị cho thấy một lần chạy được khôi phục từ checkpoint tiếp
tục giống hệt từng bit lần chạy liền mạch. Kiểm tra end-to-end đầu tiên trên máy
này không hoàn thành vì ổ đĩa đầy đúng lúc lưu checkpoint (loss trung bình của
các bước 11–20 thì khớp: 1,4489). Việc xác nhận end-to-end là một cổng bắt buộc
trên máy GPU, xem dưới.

**Dung lượng đĩa.** Mỗi thư mục kết quả giữ ba file khoảng 150, 150 và 450 MB,
và mỗi file được ghi cạnh file cũ trước khi thay thế nó. Script dừng trước khi
train nếu còn dưới 1,5 GB trống. Các file `.pth` của smoke đã được xoá;
`report.json` và `train.log` còn lại trong `models/vietocr/finetuned/`.

## Chạy trên GPU NVIDIA

**Chưa bước nào dưới đây được chạy**: máy này không có CUDA. Thứ tự là bắt buộc;
mỗi cổng FAIL thì dừng lại.

Ước lượng bộ nhớ, ngoại suy từ một lượt forward trên CPU (activations giữ lại
cho backward, gradient của chúng, bốn bản tham số cho AdamW); chưa có số đo nào
trên GPU:

| | A (512) | B (1024) |
| --- | --- | --- |
| Batch 16, mọi dòng ở chiều rộng tối đa | khoảng 4–5 GB | khoảng 7,5–9 GB |
| Dòng ở chiều rộng tối đa | 4.193 / 7.459 | 612 / 7.459 |

Mỗi experiment là 4.670 bước cộng 21 lần validation (652 dòng mỗi lần) và cần
khoảng 1,5 GB đĩa. Thời gian chưa đo được; script ghi số giây mỗi bước ngay từ
đầu.

### 0. Chuẩn bị máy và dữ liệu

```bash
git clone --recurse-submodules <repo> OCR && cd OCR
git checkout feat/vietnamese-recognizer-bakeoff
python3.12 -m venv .venv-vietocr
.venv-vietocr/bin/pip install -r benchmarks/vietnamese/recognizer_bakeoff/requirements-vietocr.txt
```

`requirements-vietocr.txt` ghim torch 2.14.1; trên Linux, bản pip mặc định của
torch đi kèm CUDA. Không cần cài gì thêm cho việc train.

Dữ liệu không nằm trong git (khoảng 260 MB, 6.219 file; **không có ảnh nào của
`blind_test`**):

```bash
# trên máy này
python datasets/vietnamese_recognition/list_training_files.py > training_files.txt
tar czf ocr_training_data.tgz -T training_files.txt
# trên máy GPU, tại gốc repo
tar xzf ocr_training_data.tgz
```

```bash
P=.venv-vietocr/bin/python
D=datasets/vietnamese_recognition
$P $D/training_inputs.py --check          # digest phải khớp, nếu không thì dừng
$P $D/check_vietocr_config.py --device cpu
$P -m unittest discover -s $D/tests -p "test_training*.py"
nvidia-smi
```

### 1. Dò batch (cổng C)

```bash
$P $D/probe_cuda_batch.py
```

Dò experiment 1024 px trước, trên những batch nặng nhất của dữ liệu train (dòng
rộng nhất, nhãn dài nhất), mỗi lần thử trong một tiến trình riêng: 16 × 1, rồi
8 × 2 nếu hết bộ nhớ, rồi 4 × 4. Batch hiệu dụng luôn là 16. Kết quả nằm trong
`models/vietocr/finetuned/batch_probe.json`: tên GPU, VRAM, phiên bản torch và
CUDA, bộ nhớ đỉnh đã cấp phát và đã giữ của từng lần thử, và dòng
`use_for_both_experiments`.

**Dùng đúng batch và số bước tích luỹ đó cho cả A và B** trong mọi bước sau
(dưới đây viết là `$B`, ví dụ `B="--batch-size 16 --accumulation-steps 1"`).
Không chạy A với batch lớn hơn B.

### 2. Cổng resume (cổng B)

```bash
$P $D/check_resume_equivalence.py --config configs/vietnamese/vietocr/exp_a_width512.yml $B
```

Ba tiến trình với đúng seed, batch, lịch và chính sách BatchNorm của lần train
thật: 40 bước liền mạch; 20 bước rồi lưu checkpoint và kết thúc; một tiến trình
mới resume và chạy bước 21–40. Ở bước 40 script so `state_dict` của model, trạng
thái optimizer, trạng thái scheduler và learning rate, số bước, và loss của từng
bước 21–40. Chỉ PASS khi mọi thứ giống hệt; chỗ nào khác thì in chênh lệch tuyệt
đối lớn nhất. `--tolerance` chỉ dùng khi đã nhìn các con số đó và quyết định chấp
nhận. **FAIL thì không train đầy đủ.**

### 3. Smoke trên CUDA (cổng D)

```bash
$P $D/train_vietocr.py --config configs/vietnamese/vietocr/exp_b_width1024.yml --smoke --run-name smoke_gpu $B
$P $D/train_vietocr.py --config configs/vietnamese/vietocr/exp_a_width512.yml  --smoke --run-name smoke_gpu $B
```

Chính sách đóng băng đã nằm trong config; thêm `--freeze-batch-norm-statistics`
cũng cho cùng kết quả. Dòng `SMOKE PASS` chỉ in ra khi: loss hữu hạn; checkpoint
pretrained nạp đủ; gradient tới mọi tensor; thống kê BatchNorm không đổi còn
gamma/beta có đổi; checkpoint và weights nạp lại khớp; `real_val` đọc được; không
manifest của tập đánh giá nào bị mở.

**Mixed precision.** `--amp` có trong script nhưng chưa từng chạy trên CUDA.
Chỉ bật sau khi một smoke với `--amp` PASS: smoke đó so loss của cùng một batch
ở hai độ chính xác (FAIL nếu lệch quá 0,01) và in cả hai. Validation luôn được
đọc ở single precision, nên `real_val` ở bước 0 phải khớp với smoke không `--amp`.
Nếu dùng thì dùng cho cả A và B, kể cả ở cổng resume.

### 4. Train đầy đủ (E)

Chỉ sau khi 1–3 PASS.

```bash
$P $D/train_vietocr.py --config configs/vietnamese/vietocr/exp_a_width512.yml  $B
$P $D/train_vietocr.py --config configs/vietnamese/vietocr/exp_b_width1024.yml $B
# bị ngắt giữa chừng: thêm --resume, tiếp tục từ lần validation gần nhất
```

Hai lần chạy chung seed, digest của input, tỉ lệ trộn, batch vật lý và hiệu
dụng, chính sách BatchNorm, optimizer, lịch learning rate, 4.670 bước, validation
mỗi 233 bước, và cùng checkpoint pretrained. Lần chạy thứ hai tự dừng nếu một
trong các điều đó khác lần thứ nhất.

### 5. Chấm và chọn (F)

```bash
$P $D/evaluate_splits.py inputs --output eval_inputs.jsonl
for exp in exp_a_width512 exp_b_width1024; do
  $P benchmarks/vietnamese/recognizer_bakeoff/run_vietocr.py \
    --config configs/vietnamese/vietocr/$exp.yml \
    --weights models/vietocr/finetuned/$exp/weights.pth \
    --manifest eval_inputs.jsonl --output predictions_$exp.jsonl --device cuda:0
  $P $D/evaluate_splits.py score --predictions predictions_$exp.jsonl --label phase4_$exp
done
$P $D/select_model.py
```

`evaluate_splits.py` không lấy crop của `blind_test` và in `blind_test: LOCKED`.
`--device cuda:0` của runner chưa được chạy thử; với `--device cpu` 752 dòng mất
vài phút và cho cùng kết quả.

`select_model.py` áp dụng đúng quy tắc, không gì khác:

1. CER thấp nhất trên `real_val`;
2. hoà thì WER thấp nhất trên `real_val`;
3. kiểm tra `bakeoff_regression`: CER không cao hơn baseline 512 (4,51%) thì
   PASS; cao hơn thì ghi `REVIEW` kèm mức tăng, để người quyết định.

Một ứng viên chỉ được chọn nếu đọc `real_val` tốt hơn baseline pretrained ở
512 px (CER 4,48%), mốc chung của cả hai experiment. Script từ chối chạy nếu một
file đánh giá có điểm của `blind_test` hoặc `blind_test` đã bị mở khoá. Quyết
định được ghi vào `manifests/evaluations/phase4_selection.json`, kèm batch, bước
tốt nhất và bộ nhớ đỉnh của từng lần train.

Sau khi chọn xong **một** config và **một** checkpoint thì dừng. `blind_test` chỉ
được mở sau đó, một lần, bằng `evaluate_splits.py score --unlock-blind-test`.

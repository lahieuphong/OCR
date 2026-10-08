# Config fine-tune VietOCR

`vgg_transformer_vi_admin.yml` là config để fine-tune VietOCR trên dataset trong
`datasets/vietnamese_recognition/`. **Chưa có gì được train bằng file này.**

File được sinh ra, không sửa bằng tay:

```bash
python datasets/vietnamese_recognition/build_vietocr_config.py            # ghi lại
python datasets/vietnamese_recognition/build_vietocr_config.py --check    # kiểm tra
```

Nó là config `vgg_transformer` của bản VietOCR đã pin
(`third_party/vietocr`, commit `fe8c3a7fc714aec57ab81cec844eb3adf0c1636c`:
`config/base.yml` gộp với `config/vgg-transformer.yml`), cộng các thay đổi liệt
kê trong `OVERRIDES` của script. Không file nào trong `third_party/vietocr` bị
sửa.

## Giá trị

| Mục | Giá trị | Pretrained | Ghi chú |
| --- | --- | --- | --- |
| Model gốc | `vgg_transformer` (VGG19-bn + Transformer) | như vậy | 37.650.217 tham số |
| Checkpoint pretrained | `models/vietocr/vgg_transformer.pth` | URL `vocr.vn` | cùng file bake-off đã đánh giá, SHA-256 `38051219…75ea59` |
| Vocab | 229 ký tự, **không đổi** | như vậy | đã đủ 178 chữ cái tiếng Việt |
| Chiều cao ảnh | 32 | 32 | |
| Chiều rộng tối đa | **1024** | 512 | xem "Vì sao 1024" |
| Batch size | 16 | 32 | xem "Bộ nhớ" |
| Learning rate (đỉnh) | **0,0001** | 0,0003 | OneCycleLR, `pct_start` 0,1 |
| Số vòng lặp | 9.500 | 100.000 | khoảng 30 epoch trên 5.059 dòng pilot |
| Validation | mỗi 320 vòng (khoảng 1 epoch), trên cả 552 dòng | | |
| Thiết bị | `cuda:0` | `cuda:0` | |
| Augmentation của VietOCR | **tắt** | bật | xem dưới |
| Masked language model | bật | bật | |
| Weights xuất ra | `models/vietocr/finetuned/vgg_transformer_vi_admin.pth` | | ngoài git |
| Checkpoint | `models/vietocr/finetuned/vgg_transformer_vi_admin_checkpoint.pth` | | ngoài git |
| Log | `models/vietocr/finetuned/train.log` | | ngoài git |

VietOCR đếm theo vòng lặp chứ không theo epoch:
`iters = số epoch × ⌈số dòng train / batch size⌉`. Đổi kích thước dataset hoặc
batch size thì phải tính lại `iters` và `valid_every`.

**Vì sao giữ nguyên vocab.** Vocab của model pretrained đã có mọi chữ cái tiếng
Việt, kể cả 88 chữ PP-OCRv6 thiếu. Đổi vocab là đổi kích thước lớp output, và
lớp đó sẽ không nạp được từ checkpoint nữa. Cái giá: model không thể xuất ký tự
ngoài 229 ký tự này (ví dụ gạch dài `–`, ngoặc kép cong, `…`). 100 dòng test
không có ký tự nào như vậy.

**Vì sao 1024.** Ở chiều cao 32 px, giới hạn 512 px nén ngang 62 trong 100 dòng
test, và 5% số dòng chỉ còn 6,5 px cho mỗi ký tự. Với 1024 px chỉ còn 1 dòng bị
nén. Chuỗi đặc trưng dài `2 × rộng / 4` = 512 vị trí, vẫn trong giới hạn 1024
của positional encoding.

Đây là một giả thuyết cần được kiểm chứng khi train, không phải điều đã biết:
model pretrained chưa từng thấy ảnh rộng hơn 512 px, và khi thử cho nó đọc ở
1024 px mà không fine-tune thì nó dừng giữa dòng. Fine-tune có dạy được nó hay
không thì chưa ai đo. Kế hoạch train nên chạy cả hai mức 512 và 1024 rồi so trên
validation.

**Vì sao learning rate thấp hơn.** Mục đích là điều chỉnh một model đã đọc tốt,
không phải dạy lại từ đầu trên vài nghìn dòng tổng hợp.

**Vì sao tắt augmentation của VietOCR.** Ảnh trong dataset đã được làm giống văn
bản scan, theo cách tái lập được từ seed. Phép biến đổi có sẵn của VietOCR còn
đảo màu 20% số ảnh và vẽ các đường kẻ màu ngẫu nhiên, những thứ không có trên
văn bản hành chính.

## Kiểm tra trước khi train

```bash
.venv-vietocr/bin/python datasets/vietnamese_recognition/check_vietocr_config.py
```

Script làm những việc một lần train sẽ làm trước bước đầu tiên rồi dừng: dựng
model, nạp checkpoint, mã hoá mọi nhãn, và chạy một lượt forward không gradient.
Không optimizer nào được tạo, không trọng số nào thay đổi.

Kết quả hiện tại:

- 0 tensor pretrained bị thiếu, 0 tensor lệch shape;
- 5.059 nhãn train và 552 nhãn validation đều mã hoá được, ảnh đều có mặt, nhãn
  dài nhất 119 ký tự (giới hạn decode là 126);
- forward ở rộng 512 và 1024 đều chạy, output `(1, 100, 233)`.

## Bộ nhớ và thời gian

Đo một lượt forward của một ảnh, trên CPU của máy này:

| Rộng | Activations | Thời gian |
| --- | --- | --- |
| 512 | 116 MB | 0,09 s |
| 1024 | 217 MB | 0,14 s |

Từ đó **ngoại suy** cho một bước train (activations giữ lại cho backward cộng
gradient của chúng, và 4 bản tham số cho AdamW). Đây là ước lượng, không phải số
đo của việc train:

| Rộng | Batch | Bộ nhớ ước tính |
| --- | --- | --- |
| 1024 | 4 | 2,3 GB |
| 1024 | 16 | 7,4 GB |
| 1024 | 32 | khoảng 14,5 GB |
| 512 | 16 | 4,2 GB |

Batch 16 ở 1024 px vừa một GPU 12 GB. VietOCR gom các ảnh cùng chiều rộng vào
một batch, nên chỉ những batch dòng dài mới chạm mức này.

## Chạy thử trên Mac M2 8 GB

Chưa chạy. Ước lượng: một smoke train rất nhỏ **chạy được**, train thật thì
không.

- Batch 4 ở 1024 px cần khoảng 2,3 GB; mỗi bước khoảng 2 giây trên CPU. Hai chục
  bước mất chưa tới một phút, đủ để thấy loss giảm và đường ống không vỡ.
- 30 epoch của bộ pilot ở batch 4 là khoảng 38.000 bước, tức gần một ngày chạy
  liên tục trên một máy đang dùng swap. Không nên.
- MPS chạy được với VietOCR nhưng ở inference nó không nhanh hơn CPU.

Môi trường `.venv-vietocr` hiện chỉ đủ cho inference. Train cần thêm các thư
viện mà `vietocr.model.trainer` import: `lmdb`, `albumentations`, `matplotlib`,
`prefetch_generator`, `six` và OpenCV. Chúng **chưa được cài**.

## Khi train (chưa làm)

```python
# chạy từ gốc repository, trong môi trường có đủ thư viện train
import sys
sys.path.insert(0, "third_party/vietocr")
from vietocr.tool.config import Cfg
from vietocr.model.trainer import Trainer

config = Cfg.load_config_from_file("configs/vietnamese/vietocr/vgg_transformer_vi_admin.yml")
trainer = Trainer(config, pretrained=True)
trainer.train()
```

Vài điều nên biết trước:

- VietOCR tạo cache LMDB `train_vi_admin_pilot_v1/` và `valid_vi_admin_pilot_v1/`
  ngay trong thư mục đang đứng. Đổi dataset mà không xoá chúng là train trên dữ
  liệu cũ.
- VietOCR chọn weights tốt nhất theo độ chính xác trên **validation**. Tập test
  đóng băng không được dùng để chọn checkpoint, chọn số vòng lặp hay chỉnh bất
  kỳ tham số nào; nó chỉ được chạy một lần ở cuối.
- Validation hiện toàn dòng tổng hợp. Nó đo được việc học trên dữ liệu tổng hợp,
  không đo được mức tốt lên trên văn bản thật. Vì thế cần thêm dòng thật đã
  verify, lấy từ tài liệu khác 3 tài liệu benchmark.
- Bộ pilot quá nhỏ để cho ra model tốt. Trước khi train thật nên sinh bộ lớn hơn
  (`build_dataset.py --scale`) với nhiều font hơn.

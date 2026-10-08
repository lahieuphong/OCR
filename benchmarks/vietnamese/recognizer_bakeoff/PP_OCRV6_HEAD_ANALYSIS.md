# PP-OCRv6_medium_rec: mở rộng head cho 88 chữ tiếng Việt

Tài liệu này trả lời câu hỏi: có thể thêm 88 chữ tiếng Việt còn thiếu vào
`PP-OCRv6_medium_rec` mà vẫn giữ được kiến thức của model pretrained không.

**Kết luận: làm được.** Chỉ 4 trong 441 tensor phụ thuộc vào từ điển. Toàn bộ
backbone và neck giữ nguyên. Các lớp cũ copy sang được, nhưng **phải copy theo
bảng ánh xạ index chứ không phải "copy N hàng đầu"**, vì lớp dấu cách bị dời
chỗ. Cần một script migration riêng; loader của PaddleOCR không tự làm việc này.

Chưa có gì được train, và không checkpoint nào được ghi ra. Mọi con số dưới đây
do `inspect_rec_checkpoint.py` đo trên code vendor và checkpoint thật, không
suy đoán. Chạy lại:

```bash
source .venv/bin/activate
python benchmarks/vietnamese/recognizer_bakeoff/inspect_rec_checkpoint.py
```

Kết quả máy đọc được nằm ở `results/ppocrv6_head_analysis.json`, danh sách đầy
đủ tên và shape của 441 tensor ở `results/ppocrv6_medium_rec_state_dict.csv`.

## Đối tượng được kiểm tra

| | |
| --- | --- |
| Checkpoint | `PP-OCRv6_medium_rec_pretrained.pdparams`, bản **training** chính thức |
| Nguồn | `https://paddle-model-ecology.bj.bcebos.com/paddlex/official_pretrained_model/PP-OCRv6_medium_rec_pretrained.pdparams` (link "Training Model" trong `PaddleOCR/docs/version3.x/pipeline_usage/OCR.md`) |
| SHA-256 | `c4a110423c23739f157ff870e27f41649d8c89e4c8df5230c2cd2e9fd90a7e92` |
| Kích thước | 232.651.336 byte, 441 tensor, 58.150.582 tham số, tất cả float32 |
| Nơi lưu | `models/pretrained/` (ngoài git) |
| Config | `PaddleOCR/configs/rec/PP-OCRv6/PP-OCRv6_medium_rec.yml` |
| Kiến trúc | backbone `PPLCNetV4` → `MultiHead` gồm `CTCHead` (neck `lightsvtr`) và `NRTRHead` |

Hai phép kiểm tra xác nhận đây đúng là checkpoint cần dùng:

- Model dựng từ config trên có đúng 441 tensor, trùng tên và shape với
  checkpoint.
- Checkpoint này, chạy ở chế độ eval trên 364 line crop của bake-off, cho ra
  text **giống hệt inference model 364/364**. Tức inference model đang dùng
  được export từ chính checkpoint này.

Checkpoint có cả nhánh NRTR (38,5 triệu tham số). Inference model không có
nhánh này, nên không thể dùng inference model thay cho training checkpoint.

## Số lớp được tính như thế nào

Config đặt `use_space_char: true`. Theo `BaseRecLabelDecode` và
`BaseRecLabelEncode`, danh sách lớp được dựng như sau:

```text
CTC   =  ["blank"]                          + <các dòng của dict> + [" "]
NRTR  =  ["blank", "<unk>", "<s>", "</s>"]  + <các dòng của dict> + [" "]
```

`tools/train.py` đặt số output của CTC bằng độ dài danh sách CTC, của NRTR bằng
con số đó cộng 3; `Transformer.__init__` cộng thêm 1 nữa
(`self.out_channels = out_channels + 1`). Hàng cuối cùng của NRTR vì thế không
ứng với ký tự nào.

| | Dict gốc (18.708 dòng) | Dict mở rộng (18.796 dòng) |
| --- | --- | --- |
| Lớp CTC | 18.710 | 18.798 |
| Lớp NRTR | 18.714 | 18.802 |

## Trả lời 9 câu hỏi

### 1. Tensor nào phụ thuộc số lớp?

Đúng 4 tensor. Chúng được tìm bằng cách dựng model hai lần (dict gốc và dict mở
rộng) rồi so shape của toàn bộ state dict, không phải bằng cách đoán theo tên.

### 2 và 3. Shape hiện tại và shape sau khi thêm 88 lớp

| Tensor | Hiện tại | Sau khi +88 | Trục lớp |
| --- | --- | --- | --- |
| `head.ctc_head.fc.weight` | (192, 18710) | (192, 18798) | 1 |
| `head.ctc_head.fc.bias` | (18710,) | (18798,) | 0 |
| `head.gtc_head.embedding.embedding.weight` | (18714, 512) | (18802, 512) | 0 |
| `head.gtc_head.tgt_word_prj.weight` | (512, 18714) | (512, 18802) | 1 |

Tổng cộng thêm 88 × (192 + 1 + 512 + 512) = 107.096 tham số.

### 4. Có giữ nguyên được backbone và neck không?

Có. 437 tensor còn lại không đổi shape: 314 tensor của backbone và 123 tensor
của head (neck `lightsvtr`, `before_gtc`, 4 tầng decoder của NRTR). Với trọng
số được migrate, đặc trưng sau neck của model mở rộng khác model gốc **0** (sai
khác lớn nhất trên 364 crop).

### 5. Có copy được trọng số classifier cũ theo index gốc không?

Có, với **một ngoại lệ bắt buộc phải xử lý**.

Dict mở rộng giữ nguyên số dòng của mọi entry cũ, nên các lớp `blank` và 18.708
ký tự giữ nguyên index. Nhưng lớp dấu cách không nằm trong file dict: nó được
gắn vào **sau** dòng cuối cùng. Khi thêm 88 dòng, nó bị đẩy xuống cuối:

| Head | Giữ nguyên index | Lớp mới | Lớp bị dời |
| --- | --- | --- | --- |
| CTC | 18.709 lớp (0 … 18708) | 18709 … 18796 | `" "`: 18709 → **18797** |
| NRTR | 18.712 lớp (0 … 18711) | 18712 … 18799 | `" "`: 18712 → **18800**; hàng thừa: 18713 → 18801 |

Nếu chỉ copy 18.710 hàng đầu của CTC vào đúng vị trí cũ thì trọng số của dấu
cách sẽ rơi vào lớp của chữ `ạ` (index 18709), còn lớp dấu cách thật (18797) bị
khởi tạo ngẫu nhiên. Model sẽ in `ạ` ở mọi chỗ có dấu cách.

Khi copy theo bảng ánh xạ ký tự → index, logit của mọi lớp cũ ở model mở rộng
khác model gốc **0** (sai khác lớn nhất trên 364 crop).

### 6. Các hàng mới nên khởi tạo thế nào?

Đo trên 364 crop, trước khi train bất cứ thứ gì, với ba cách khởi tạo hàng CTC
của 88 lớp mới:

| Khởi tạo hàng mới | Crop giữ nguyên text | Time step bị lớp mới thắng |
| --- | --- | --- |
| Ngẫu nhiên, theo initializer của head (`Uniform(±1/√192)`) | 231 / 364 | 223 |
| "Im lặng": weight = 0, bias = bias thấp nhất của lớp cũ (−0,07) | 364 / 364 | 0 |
| Copy từ chữ gần nhất đã có (`ạ` ← `a`, `ệ` ← `ê`, `ờ` ← `ơ`) | 364 / 364 | 0 |

Khởi tạo ngẫu nhiên **làm hỏng output của model pretrained ngay từ bước 0**:
hơn một phần ba số dòng đổi text. Lý do: ở những vị trí có chữ mà model không có
lớp, logit của mọi lớp cũ đều thấp, nên một lớp ngẫu nhiên dễ dàng thắng.

Hai cách còn lại đều giữ nguyên hành vi. Chúng khác nhau ở điểm xuất phát của
việc học, điều mà phép đo này không so sánh được:

- "Im lặng" là cách trung tính nhất: lớp mới không ảnh hưởng gì cho tới khi dữ
  liệu dạy nó.
- Copy từ chữ gần nhất cho lớp mới một điểm xuất phát có nghĩa (cùng chữ gốc),
  nhưng lớp mới hoà điểm chính xác với lớp nguồn; hiện lớp cũ thắng chỉ vì
  `argmax` lấy index nhỏ hơn. Chọn cách này thì nên trừ một lượng nhỏ vào bias
  của lớp mới để không phụ thuộc vào việc phá thế hoà.

Chọn cách nào là quyết định của Phase 3B. Điều đã chắc chắn: **không dùng khởi
tạo ngẫu nhiên**.

### 7. Embedding và output layer của NRTR có cần mở rộng không?

Có, cả hai: `embedding.embedding.weight` (trục 0) và `tgt_word_prj.weight`
(trục 1), cùng bảng ánh xạ index của NRTR. Hai tensor này không chia sẻ trọng
số với nhau.

Nhánh NRTR chỉ chạy khi train: `MultiHead.forward` trả về kết quả CTC ngay khi
`not self.training`. Nó không ảnh hưởng tới inference, nhưng nó tham gia loss
(`MultiLoss` = `CTCLoss` + `NRTRLoss`), nên nếu để nó khởi tạo ngẫu nhiên thì
gradient từ nhánh này sẽ kéo lệch backbone trong giai đoạn đầu của fine-tune.
Vì vậy vẫn nên migrate nó. Cách khởi tạo hàng mới của NRTR chưa được đo ở đây,
do không thể chạy nhánh này ở chế độ eval.

### 8. Loader của Paddle xử lý lệch shape ra sao?

`load_pretrained_params` (`PaddleOCR/ppocr/utils/save_load.py`, dùng khi đặt
`Global.pretrained_model`) so shape từng tensor; tensor nào lệch thì ghi một
dòng `WARNING` rồi **bỏ qua**, sau đó vẫn báo `load pretrain successful`. Nhánh
`Global.checkpoints` trong `load_model` có cùng logic (đọc từ source, chưa chạy
thử).

Chạy thật trên model mở rộng: 4 cảnh báo, và đúng 4 tensor phụ thuộc từ điển bị
để nguyên ở giá trị khởi tạo ngẫu nhiên; 437 tensor còn lại được nạp.

Hệ quả nếu chỉ đổi `character_dict_path` rồi fine-tune: việc train không báo
lỗi, nhưng toàn bộ classifier của **18.710 lớp** bị bỏ, không chỉ 88 lớp mới.
Model phải học lại từ đầu cách phân biệt mọi ký tự, kể cả chữ Latin và chữ số
mà nó vốn đã đọc tốt.

### 9. Có cần viết script migration checkpoint không?

Có, bắt buộc, vì câu 5 và câu 8. Script đó cần:

1. Dựng danh sách lớp của dict gốc và dict mở rộng bằng chính label codec của
   PaddleOCR, rồi ánh xạ lớp cũ sang lớp mới **theo ký tự**.
2. Với 4 tensor ở trên, tạo tensor shape mới, copy các lớp cũ vào vị trí mới
   theo trục lớp, và khởi tạo 88 hàng mới theo cách đã chọn ở câu 6.
3. Giữ nguyên 437 tensor còn lại.
4. Tự kiểm tra trước khi ghi file: logit lớp cũ khác model gốc 0, và text decode
   không đổi trên một tập crop.

`inspect_rec_checkpoint.py` đã làm đủ cả bốn bước này trong bộ nhớ, nên phần
logic đã được chứng minh; việc còn lại của Phase 3B là ghi kết quả ra file
`.pdparams`.

## Những điều phải xử lý ở Phase 3B

Ba điểm sau không chặn việc migrate head, nhưng sẽ làm hỏng fine-tune nếu bỏ
qua. Cả ba đều đọc được từ config và code vendor.

**`max_text_length: 25` loại gần hết dữ liệu dòng.** `BaseRecLabelEncode.encode`
trả về `None` khi nhãn dài hơn `max_text_length`, và `NRTRLabelEncode` loại nhãn
từ 24 ký tự trở lên; mẫu bị loại sẽ biến mất khỏi tập train mà không có cảnh
báo. Trong 364 dòng của bake-off, khoảng 306 dòng dài từ 24 ký tự (ước lượng
theo output của VietOCR; trung vị 70, dài nhất 102). Phải tăng `max_text_length`
ở cả `Global` và `NRTRHead`. Đã kiểm tra: dựng model với `max_text_length: 120`
không làm đổi shape tensor nào, nên checkpoint vẫn nạp được.

**Kích thước ảnh train quá hẹp cho dòng dài.** Config train với các scale rộng
320 px (cao 32, 48, 64), trong khi dòng văn bản ở đây có tỉ lệ rộng/cao trung vị
26. Cần nới chiều rộng train, hoặc cắt dòng thành đoạn ngắn hơn.

**Ký tự không có trong dict bị bỏ khỏi nhãn một cách âm thầm.** `encode` dùng
`continue` với ký tự lạ. Nếu fine-tune tiếng Việt với dict gốc, nhãn
`Căn cứ Luật` sẽ thành `Căn c Lut`, tức dạy model bỏ qua đúng những chữ cần
học. Dict mở rộng giải quyết việc này; nên thêm bước kiểm tra rằng mọi ký tự
trong nhãn train đều có trong dict.

## Không được làm

Không trỏ `character_dict_path` của inference model pretrained vào
`ppocrv6_vi_ext_dict.txt`. Output head của model đó vẫn có 18.710 lớp. Kết quả
duy nhất là index 18709, vốn là dấu cách, sẽ được in ra thành `ạ`. Dict mở rộng
chỉ đúng với một model đã được mở rộng số lớp, migrate checkpoint, fine-tune và
export lại.

## Phương án thay thế chưa chọn

Có thể tránh việc lớp dấu cách bị dời bằng cách đặt `use_space_char: false` và
ghi dấu cách thành một dòng của dict, ngay sau 18.708 dòng gốc và trước 88 chữ
mới. Khi đó mọi lớp cũ giữ nguyên index và migration chỉ là copy phần đầu.

Phương án này không được dùng vì nó trái với quy tắc của dict mở rộng (dict gốc
nguyên vẹn cộng đúng 88 dòng ở cuối) và đổi thêm một tham số của config. Bảng
ánh xạ theo ký tự xử lý được cả hai trường hợp, nên không cần đánh đổi.

# Cấu hình tiếng Việt

## `ppocrv6_vi_ext_dict.txt`

Từ điển ký tự cho việc fine-tune `PP-OCRv6_medium_rec` về sau:

```text
ppocrv6_vi_ext_dict.txt  =  PaddleOCR/ppocr/utils/dict/ppocrv6_dict.txt (nguyên vẹn từng byte)
                            + 88 chữ tiếng Việt còn thiếu, mỗi chữ một dòng, ở cuối
```

| | Dòng | SHA-256 |
| --- | --- | --- |
| Dict gốc | 18.708 | `b5f2bfe2bdd9448429e3e82b51c789775d9b42f2403d082b00662eb77e401c5d` |
| Dict mở rộng | 18.796 | `3f90319ec2b643de5122efe7f4c263ba77141d8d637297098a6939eb5dd9e653` |

Không dòng nào của dict gốc bị đổi chỗ, xoá, sắp xếp lại hay chuẩn hoá, nên mọi
entry cũ giữ nguyên số dòng. 88 chữ mới được xếp theo thứ tự code point, từ `ạ`
(U+1EA1) tới `ỹ` (U+1EF9).

File này được sinh ra, không sửa bằng tay:

```bash
python benchmarks/vietnamese/audit_charset.py                 # liệt kê 88 chữ thiếu
python benchmarks/vietnamese/build_extended_dict.py           # ghi lại file
python benchmarks/vietnamese/build_extended_dict.py --check   # kiểm tra file còn đúng
```

`vi_dict.txt` của PaddleOCR không được dùng: nó là một từ điển khác hẳn (113
dòng), thay nó vào sẽ đổi index của mọi lớp.

### Chỉ dùng cho training

**Không trỏ `character_dict_path` của model pretrained vào file này.** Model
pretrained có 18.710 lớp output và không có lớp nào cho 88 chữ mới. Đổi từ điển
không làm nó đọc được các chữ đó; nó chỉ làm sai nhãn của output: lớp dấu cách
(index 18709) sẽ được in ra thành `ạ`.

File này chỉ đúng với một model mà:

1. kiến trúc đã được dựng với số lớp mới;
2. checkpoint đã được migrate sang số lớp mới;
3. đã được fine-tune và export lại.

### Lớp dấu cách bị dời khi mở rộng

Giữ nguyên số dòng không có nghĩa là mọi lớp giữ nguyên index. Với
`use_space_char: true`, PaddleOCR gắn lớp dấu cách vào **sau** dòng cuối của
dict, nên thêm 88 dòng sẽ đẩy nó từ index 18709 xuống 18797 (CTC). Khi migrate
checkpoint phải copy trọng số theo ký tự, không phải theo vị trí. Chi tiết và số
liệu đo: `benchmarks/vietnamese/recognizer_bakeoff/PP_OCRV6_HEAD_ANALYSIS.md`.

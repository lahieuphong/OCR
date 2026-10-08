# Ground truth

Văn bản đúng của từng trang, **do người đọc và kiểm tra**. Đây là chuẩn để đo
CER/WER, nên mọi con số benchmark chỉ đáng tin bằng đúng mức thư mục này đáng
tin.

## Quy tắc

- Ground truth không được sinh bằng OCR, từ điển, language model hay LLM.
- Output OCR chỉ được dùng làm **bản nháp** (candidate) để người sửa.
- Một trang chỉ được chấm điểm khi đã có người kiểm tra và ghi nhận
  `verified: true`. Candidate chưa kiểm tra không bao giờ được dùng làm chuẩn.
- Trang đã verified không bị script nào ghi đè.

## Cấu trúc

```text
ground_truth/pages/<document>/
├── page_0001.txt     # văn bản đúng của trang 1, UTF-8
├── page_0002.txt
└── metadata.json     # ai kiểm tra, khi nào, hash của file lúc kiểm tra
```

`<document>` trùng với tên thư mục output của tài liệu (tên file không kèm đuôi).

`metadata.json` do lệnh `verify` ghi, không cần sửa tay:

```json
{
  "document": "<document>",
  "input": {"name": "<tên file gốc>", "sha256": "<hash của file gốc>"},
  "pages": {
    "page_0001": {
      "verified": true,
      "verified_by": "<tên người kiểm tra>",
      "verified_at": "<thời điểm, UTC>",
      "sha256": "<hash của page_0001.txt lúc kiểm tra>",
      "source_profile": "<profile sinh ra candidate>",
      "candidate_sha256": "<hash của candidate OCR chưa sửa>",
      "identical_to_candidate": false
    }
  }
}
```

File gốc không nằm trong git, nên `input.sha256` là thứ gắn ground truth với
đúng một file cụ thể.

Script đánh giá chỉ dùng một trang khi `verified` là `true` **và** hash của file
hiện tại khớp với `sha256` đã ghi. Sửa file sau khi verify sẽ làm trang đó bị
bỏ qua cho tới khi verify lại.

`identical_to_candidate: true` nghĩa là văn bản được xác nhận giống hệt output
OCR chưa sửa. Điều đó chỉ đúng nếu OCR không sai chữ nào trên trang; với người
audit, đây là dấu hiệu cần xem lại trang đó.

## Quy trình

1. Tạo candidate từ output của một profile:

   ```bash
   python benchmarks/vietnamese/prepare_ground_truth.py candidates \
     --profile ppocrv6_vi_unwarp_off
   ```

   Kết quả nằm ở `benchmarks/vietnamese/annotation_candidates/<document>/`:
   `page_XXXX.txt` là text OCR giữ nguyên, `page_XXXX.png` là ảnh của trang.

2. Mở từng cặp `page_XXXX.png` và `page_XXXX.txt`, sửa file text cho khớp với
   ảnh (xem quy ước bên dưới).

3. Ghi nhận trang đã kiểm tra:

   ```bash
   python benchmarks/vietnamese/prepare_ground_truth.py verify \
     --document <document> --page 1 --verified-by "<tên của bạn>"
   ```

   Lệnh này chép file đã sửa sang `ground_truth/pages/<document>/` và ghi
   `verified: true`. Chỉ chạy cho trang đã đọc đối chiếu từng dòng với ảnh.

4. Muốn sửa một trang đã verify: sửa trực tiếp file trong `ground_truth/pages/`
   rồi chạy lại lệnh `verify` cho trang đó.

Chạy lại bước 1 không ghi đè candidate đã được sửa tay (trừ khi thêm `--force`)
và bỏ qua các trang đã verified.

## Quy ước gõ ground truth

Các quy ước này cần giữ thống nhất giữa mọi trang, vì CER so sánh từng ký tự:

- Gõ đúng những gì in trên trang, kể cả lỗi chính tả của văn bản gốc. Không tự
  sửa nội dung văn bản.
- Giữ nguyên hoa/thường, dấu câu và dấu tiếng Việt.
- Mỗi dòng in trên trang là một dòng trong file, theo thứ tự đọc từ trên xuống,
  trái sang phải. Candidate đã theo thứ tự OCR nhận ra; nếu thứ tự đó sai so với
  thứ tự đọc thì sửa lại.
- Giữa các từ dùng đúng một dấu cách. Không thêm dòng trống.
- Quyết định một lần rồi áp dụng cho mọi trang: có gõ hay không phần chữ trong
  con dấu, chữ viết tay, chữ ký số ở đầu trang. Ghi quyết định đó vào file này.

Lưu ý khi đọc kết quả: candidate lấy từ một profile, nên cách ngắt dòng và thứ
tự dòng của ground truth sẽ gần với profile đó hơn. CER tính cả ký tự xuống
dòng, vì vậy profile còn lại có thể bị tính thêm lỗi chỉ vì ngắt dòng khác. WER
tách từ theo khoảng trắng nên không bị ảnh hưởng bởi cách ngắt dòng.

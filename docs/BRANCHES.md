# Kiểm kê nhánh và worktree

Đối chiếu trực tiếp GitHub và local ngày **26/10/2026**. Trước dọn: 21 nhánh remote, main tại d2eedbd0d47159532793ca77e392e6c868933c2a. Sau dọn: **10 nhánh remote**, gồm main và 9 nhánh nghiên cứu/base được giữ.

Chủ dự án chọn giữ nghiên cứu, chỉ dọn phần trùng. PR #1–7 vẫn mở, head/base không bị thay đổi. PR #10 được đóng vì phần packaging đã được #11 tích hợp/thay thế.

## Toàn bộ nhánh tại thời điểm kiểm tra

SHA dưới đây là tip **trước lần dọn**, không phải cam kết tip hiện tại của main.

| Nhánh | SHA trước dọn | Xử lý | Bằng chứng / lý do |
|---|---|---|---|
| docs/vietocr-b1024-pretrained-provenance | 26fa164e | Đã dọn remote | Đã tích hợp qua PR #13; merge commit có trên main. |
| feat/local-pdf-ocr-demo | 19e07e5d | Đã dọn remote | Checkpoint được giữ đầy đủ trong lịch sử H1. |
| feat/local-pdf-ocr-header-split-exp | f6461537 | Giữ | Base của PR nghiên cứu #1. |
| feat/local-pdf-ocr-layout-v2 | 521fb293 | Đã dọn remote | Checkpoint được giữ đầy đủ trong lịch sử H1. |
| feat/vietdoc-community-release-readiness | 04357a62 | Đã dọn remote | Đã tích hợp qua PR #12; merge commit có trên main. |
| feat/vietdoc-electron-windows | f7ca25f9 | Đã dọn remote | Bản cũ đã được PR #9 thay thế. |
| feat/vietdoc-gtv2-hybrid-h1 | 7e1e6dcb | Giữ | PR nghiên cứu #7; giữ lịch sử nghiên cứu/checkpoint trước đó. |
| feat/vietdoc-offline-installer-poc | b69438ce | Đã dọn remote | Đã tích hợp qua PR #11; merge commit có trên main. |
| feat/vietdoc-windows-packaging | b9256791 | Đã dọn remote | Bản cũ đã được PR #11 thay thế. |
| feat/vietnamese-baseline | 2db82afc | Đã dọn remote | Checkpoint được giữ đầy đủ trong lịch sử H1. |
| feat/vietnamese-recognizer-bakeoff | 9f78c776 | Giữ | Nhánh nghiên cứu model đang có worktree local và thay đổi chưa chốt. |
| feat/vietocr-b1024-onnx-parity | 0f90991a | Đã dọn remote | Checkpoint được giữ đầy đủ trong lịch sử H1. |
| feat/vietocr-document-number-probe | 27fe6108 | Giữ | PR nghiên cứu #3; base của #4. |
| feat/vietocr-number-prefix-fallback-qa | e029435d | Giữ | PR nghiên cứu #6; base của #7. |
| feat/vietocr-number-review-triage | 901874dc | Giữ | PR nghiên cứu #4; base của #5. |
| feat/vietocr-number-review-ui-exp | eb064440 | Giữ | PR nghiên cứu #5; base của #6. |
| feat/vietocr-recognition-quality-exp | a55b69db | Giữ | PR nghiên cứu #1; base của #2. |
| feat/vietocr-zone-aware-qa | f7057207 | Giữ | PR nghiên cứu #2; base của #3. |
| integration/vietdoc-b1024-app | 2abb71e1 | Đã dọn remote | Đã tích hợp qua PR #8; merge commit có trên main. |
| integration/vietdoc-electron-main | 567e4d87 | Đã dọn remote | Đã tích hợp qua PR #9; merge commit có trên main. |
| main | d2eedbd0 | Giữ | Nguồn ứng dụng hiện hành. |

Các PR tích hợp dùng squash hoặc import source nên không dùng riêng `git branch --merged` để kết luận. Việc dọn đã kiểm SHA head/PR, merge commit có trên main, ancestry ở nhánh giữ lại và các đường dẫn code desktop được giữ/nâng cấp. Remote deletion kiểm SHA bằng lease, thực hiện atomic; không rewrite main.

## Local

- Xóa 3 local branch không checkout và đã được thay thế/tích hợp: feat/vietdoc-electron-windows, integration/vietdoc-b1024-app, integration/vietdoc-electron-main.
- Dọn worktree VietDoc_clean_main sau khi sửa registration trỏ vị trí cũ: HEAD 6eeae584 đã có trong main, không thay đổi local hoặc ignored data.
- Dọn worktree OCR_vietdoc_fixcheck: commit scratch 87393cf chỉ mô phỏng cherry-pick; patch-id khớp e170465, đã được giữ trong H1. Parent/submodule sạch, không có ignored data.
- Sửa liên kết submodule Git local trỏ sai vị trí. Worktree OCR_vietdoc_integration được giữ, source và thay đổi local không sửa.
- Dọn tiếp ngày 26/10/2026: gỡ hai worktree sạch `OCR_vietdoc_electron_app` và `OCR_vietdoc_installer_poc`; phần ignored chỉ gồm dependency/build tái tạo được. Giữ local branch `integration/vietdoc-electron-app` tại `5d6cefd6` và `feat/vietdoc-offline-installer-poc` tại `b69438ce` để có thể khôi phục source.
- Còn 5 worktree/7 local branch. Ba worktree nghiên cứu `OCR_vietdoc_gtv2_h1`, `OCR_vietdoc_integration`, `OCR_vietdoc_packaging` có thay đổi local nên được giữ nguyên; worktree gốc cũng còn nghiên cứu chưa commit. Nguồn ứng dụng hiện hành là `VietDoc_main_review_20261024`.
- Main hiện nằm tại `OCR/VietDoc_main_review_20261024`; đã sửa registration bằng `git worktree repair` sau khi chuyển thư mục vào `OCR`. Làm việc trên ứng dụng từ worktree này.
- Kiểm tra bổ sung 26/10/2026: dọn output build trong quarantine, installer lịch sử và môi trường UI QA không còn dùng. Giữ bản cài hiện hành, model/dữ liệu, source khôi phục, bằng chứng QA và các thay đổi nghiên cứu.
- Worktree nghiên cứu gốc còn các staged/unstaged/untracked changes. Không reset/stash/clean hoặc pull tự động để làm status xanh.

Không ghi private document, nhãn blind, model hoặc cấu hình riêng vào tài liệu kiểm kê này.

## Quy tắc dọn về sau

1. Phân biệt main hiện hành, PR nghiên cứu đang mở và bản sao/checkpoint lịch sử.
2. Chỉ bỏ nhánh đã tích hợp khi head không tiến thêm; với squash phải đối chiếu PR/merge commit và source.
3. Chỉ bỏ checkpoint khi commit vẫn được nhánh giữ lại chứa; không đổi base của PR nghiên cứu vì muốn giảm số nhánh.
4. Trước khi bỏ worktree, kiểm cả thay đổi tracked, untracked, ignored và submodule. Không dùng force để bỏ công việc chưa chốt.
5. Model lock, security/auth, schema metadata/Excel và quyền phân phối vẫn phải được kiểm riêng khi thay code.

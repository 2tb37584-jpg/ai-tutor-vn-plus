# ChatGPT Plus Project Setup — AI Tutor VN

## Mục tiêu
Dùng ChatGPT Project làm trung tâm điều phối phát triển dài hạn. Không dùng Codex để tự đọc toàn bộ repo ở mỗi lượt.

## Tên Project đề xuất
`AI Tutor VN — Product & Engineering`

## Memory
Chọn `Project-only memory` để giữ ngữ cảnh phát triển tập trung trong dự án.

## Project Instructions
Dán toàn bộ nội dung trong `CHATGPT_PROJECT_INSTRUCTIONS.md` vào Project settings → Project instructions.

## File upload ban đầu
Chỉ upload các file trong thư mục `chatgpt_project_pack/`. Không upload toàn bộ source code.

Lý do:
- Project cần giữ kiến trúc, quyết định, roadmap và task state lâu dài.
- Source code thay đổi thường xuyên nên Git/repo là nguồn sự thật tốt hơn.
- Khi cần review một module, chỉ upload hoặc đính kèm các file liên quan của module đó.

## Quy tắc hội thoại
Mỗi chat trong Project chỉ nên có một mục đích chính:
- `00 — Project Control`: trạng thái, quyết định, ưu tiên.
- `01 — Architecture`: kiến trúc và technical decisions.
- `02 — Tutor Engine`: thiết kế cơ chế gia sư.
- `03 — Curriculum & Skills`: taxonomy/knowledge graph.
- `04 — Verification`: math verifier.
- `05 — Mastery`: mastery/misconception.
- `06 — Evaluation`: eval suite và metrics.
- `07 — Frontend`: UX/UI.
- `08 — Bugs & Integration`: lỗi tích hợp.

Không tạo một chat duy nhất chứa toàn bộ lịch sử phát triển.

## Codex
Chỉ mở Codex khi đã có ticket trong `tasks/` với:
- Goal
- Allowed files
- Constraints
- Acceptance criteria
- Targeted tests

Nếu ticket chưa đủ 5 phần trên, chưa dùng Codex.

# AI Tutor VN — Development Workflow

## Purpose

Tăng tốc phát triển mà không giảm chất lượng, không mở rộng scope tùy tiện, và không làm mất các cổng kiểm tra quan trọng của AI Tutor VN.

Nguyên tắc chính:

- tự động hóa thao tác lặp;
- giữ task nhỏ và có acceptance criteria rõ ràng;
- dùng test/eval theo tầng để rút ngắn feedback loop;
- ChatGPT làm architecture, decomposition, review, test/eval design và documentation;
- Codex chủ yếu implementation/debugging trong scope hẹp;
- Git repository vẫn là source of truth cho code;
- không chạy live LLM eval tốn credits nếu unit/integration test có thể phát hiện lỗi trước.

---

## 1. Standard development loop

Luồng chuẩn:

```text
Task ACTIVE
→ xác định micro-task
→ viết spec/Codex prompt
→ implementation
→ fast targeted test
→ review packet
→ ChatGPT review diff
→ integration/full test
→ commit
→ đóng task
→ chọn task kế tiếp
```

Không commit implementation trước khi diff được review.

Không mở task mới khi task ACTIVE hiện tại chưa đạt acceptance criteria.

---

## 2. One-command developer layer

Mục tiêu là thay các chuỗi PowerShell lặp đi lặp lại bằng các lệnh ngắn, dễ nhớ.

### Before M00-06

Các lệnh ở đây là các chuỗi PowerShell thủ công; developer command layer chưa tồn tại.

### After M00-06

Developer command layer có sẵn tại repository root:

```powershell
.\dev.ps1 status
.\dev.ps1 test eval
.\dev.ps1 test full
.\dev.ps1 review
.\dev.ps1 snapshot
```

Các lệnh hiện có chỉ phục vụ kiểm tra và test. Task lifecycle automation như `task status`,
`task start`, và `task done` chưa được triển khai; chúng thuộc M00-07.

### Windows execution policy

Nếu PowerShell chặn việc chạy script, dùng override chỉ cho terminal hiện tại:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
```

`Scope Process` chỉ ảnh hưởng PowerShell process hiện tại và tự mất khi đóng terminal.
Không cần thay đổi execution policy ở cấp machine hoặc user vĩnh viễn.

### `status`

Nên hiển thị tối thiểu:

- Git HEAD;
- working tree;
- task ACTIVE;
- Docker service status cơ bản;
- không in API key hoặc secret.

### `test eval`

Chạy deterministic eval target hiện tại:

```powershell
docker compose exec backend pytest -q tests/test_eval_runner.py
```

Không gọi live provider mặc định.

### `test full`

Chạy full backend regression suite.

Có thể mở rộng frontend test/build sau khi frontend test suite đủ ổn định.

### `review`

Chạy tối thiểu:

```text
git diff --check
git diff --stat
git status --short
```

Có thể bổ sung danh sách file thay đổi.

### `snapshot`

Tạo project snapshot ngắn, không chứa secrets, ví dụ:

```text
HEAD: <sha>
ACTIVE: M09-13
Git: clean
Backend tests: pass
Eval corpus: 100
Phase: late Phase 1
Provider API mode: chat_completions
```

Snapshot dùng để bắt đầu chat mới hoặc khôi phục context nhanh.

Không bao giờ ghi API key vào snapshot.

Snapshot chỉ in metadata provider an toàn (`API_MODE`) khi backend Docker đang khả dụng;
không in `.env`, environment variables, hoặc API key.

---

## 3. Three-tier test strategy

Không dùng full test/live eval cho mọi thay đổi nhỏ.

### Tier 1 — Fast gate

Chạy sau mỗi implementation nhỏ.

Ví dụ:

```text
unit test đúng module
targeted regression test
```

Mục tiêu: phản hồi trong vài giây.

### Tier 2 — Integration gate

Chạy khi task implementation sắp hoàn tất.

Ví dụ:

```text
full backend test suite
frontend build/test nếu task liên quan frontend
git diff --check
```

Mục tiêu: phát hiện regression trước commit.

### Tier 3 — Live model gate

Chỉ dùng khi thay đổi có thể ảnh hưởng hành vi LLM, prompt, structured output, provider compatibility hoặc eval semantics.

Thứ tự ưu tiên:

```text
representative subset (ví dụ 10 cases)
→ review failures
→ full 100-case live baseline tại milestone
```

Không chạy 100 live cases chỉ để phát hiện lỗi mà unit test có thể bắt được.

---

## 4. Task lifecycle automation

Mục tiêu dài hạn là tránh sửa task status thủ công ở nhiều file.

Interface đề xuất:

```text
task status
task start Mxx-yy
task done Mxx-yy
```

Automation nên:

- đọc `TASK_INDEX.md`;
- xác nhận tối đa một task ACTIVE;
- đồng bộ status giữa task file và `TASK_INDEX.md`;
- từ chối `done` nếu acceptance criteria/checklist chưa được xác nhận;
- không tự chọn task mới nếu source of truth chưa chỉ định;
- không sửa code sản phẩm.

Cho đến khi automation này được implement, tiếp tục cập nhật task-control thủ công và review diff trước commit.

---

## 5. Codex review packet

Mỗi task Codex sau implementation nên trả về một packet chuẩn:

```text
FILES_CHANGED
IMPLEMENTATION_SUMMARY
TEST_TARGETED
TEST_FULL
DIFF_STAT
GIT_STATUS
KNOWN_RISKS
```

Nếu test chưa chạy hoặc fail, phải nói rõ.

Codex không commit trừ khi task spec cho phép rõ ràng.

ChatGPT review diff trước commit.

---

## 6. Codex scope rules

Mỗi Codex task mặc định:

- 1 goal;
- 1 micro-task logic;
- khoảng 2–6 allowed files;
- explicit forbidden scope;
- acceptance criteria;
- targeted tests;
- stop conditions.

Codex phải dừng và báo lại nếu:

- cần file ngoài allowed scope;
- cần dependency mới;
- cần thay kiến trúc;
- cần schema/database migration ngoài dự kiến;
- task phát triển thành nhiều subsystem;
- acceptance criteria mơ hồ.

Nếu task phình to, tách task mới thay vì mở rộng vô hạn.

---

## 7. Project snapshot instead of hand-maintained current state

`08_CURRENT_STATE.md` có thể bị stale nếu cập nhật bằng tay.

Hướng ưu tiên:

- repository/task index = source of truth;
- `snapshot` được sinh tự động từ repo;
- Project documentation chỉ lưu architecture, rules và decisions bền vững;
- trạng thái runtime/ngày hiện tại nên được generated thay vì copy tay.

Snapshot phải ngắn và an toàn để paste vào ChatGPT.

---

## 8. CI policy

Khi GitHub CI được thiết lập, nên tự động chạy trên push/PR:

```text
diff/lint checks
backend tests
frontend tests/build
offline eval regression
```

Không chạy live paid-model eval trên mọi commit/PR.

Live eval nên:

- manual;
- milestone-triggered;
- hoặc chạy khi thay đổi prompt/provider/tutor behavior thực sự cần.

---

## 9. Secrets and student-data safety

Automation không được:

- in API key;
- lưu API key vào snapshot;
- commit `.env`;
- log dữ liệu học sinh không cần thiết;
- đưa raw student PII vào eval fixtures.

Các lệnh kiểm tra config chỉ nên in boolean/config metadata không nhạy cảm.

---

## 10. What NOT to do for speed

Không tăng tốc bằng cách:

- chuyển sang microservices khi chưa có bằng chứng cần thiết;
- cho Codex tự do đọc/sửa toàn repo;
- bỏ unit tests;
- bỏ ChatGPT diff review;
- chạy live LLM eval thay cho deterministic tests;
- thêm framework/dependency chỉ để “tiện” mà chưa có ROI rõ;
- gom nhiều thay đổi logic khác nhau vào cùng một task.

Mục tiêu là giảm thao tác lặp, không giảm kỷ luật kỹ thuật.

---

## 11. Adoption plan

### Current task

Tiếp tục hoàn thành:

```text
M09-18 — Refine Primary-Skill Specificity Precedence
```

Không chen implementation workflow automation vào M09-18. M09-18 phải đạt acceptance criteria, targeted/full tests và targeted live validation trước khi đóng.

### Mandatory next workflow-improvement milestone

Ngay sau khi M09-18 hoàn tất và task-control sạch, **không mở thêm M09 implementation task mới trước khi thực hiện workflow automation**, trừ khi M09-18 phát hiện một blocker nghiêm trọng bắt buộc phải sửa để giữ repository ở trạng thái an toàn.

Task kế tiếp được ưu tiên bắt buộc:

```text
M00-06 — Developer Workflow Automation
```

M00-06 phải triển khai developer command layer thực tế, không chỉ là tài liệu.

Scope đầu tiên:

1. `dev.ps1` với:
   - `status`;
   - `review`;
   - `test eval`;
   - `test full`;
   - `snapshot`;
2. tài liệu usage ngắn;
3. không dependency mới nếu không cần;
4. mặc định 2–4 files;
5. không thay đổi business logic;
6. không gọi live paid-model eval mặc định;
7. không in secret/API key;
8. output phải đủ ngắn để paste lại vào ChatGPT.

Sau M00-06, ưu tiên task riêng:

```text
M00-07 — Task Lifecycle Automation
```

M00-07 dự kiến cung cấp:

```text
task status
task start Mxx-yy
task done Mxx-yy
```

để đồng bộ `TASK_INDEX.md` và task file, tránh tình trạng một nơi `DONE` nhưng task file vẫn `ACTIVE`.

### Enforcement until M00-06 is complete

Cho đến khi M00-06 được implement:

- tiếp tục dùng workflow thủ công hiện tại;
- không coi các command trong mục 2 là đã tồn tại;
- không ghi nhận `dev.ps1` là available nếu file chưa có trong Git;
- mọi commit vẫn phải qua targeted test, diff review và full test theo scope;
- sau M09-18, ưu tiên M00-06 trước khi tiếp tục mở rộng Phase 1/Phase 2.

---

## 12. Success criteria for the workflow

Workflow mới được coi là có ích khi:

- số lệnh thủ công mỗi checkpoint giảm rõ rệt;
- không tăng regression;
- task status ít bị lệch;
- chat mới khôi phục context nhanh bằng snapshot;
- live API credits không bị tiêu cho lỗi deterministic;
- Codex task vẫn nhỏ và reviewable;
- source of truth vẫn là Git repository.

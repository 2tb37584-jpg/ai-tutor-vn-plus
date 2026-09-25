# AI Tutor VN — Development Workflow

Version: 2026-09-25
Mode: GitHub PR-based handoff

## Purpose

Tài liệu này là protocol phát triển bền vững cho AI Tutor VN.

Mục tiêu:

- giữ GitHub/Git repository là source of truth;
- cho phép đổi ChatGPT account mà không mất trạng thái dự án;
- tách rõ vai trò ChatGPT và Codex;
- để Codex implementation trên branch riêng và bàn giao bằng Pull Request;
- bắt buộc ChatGPT review trước task DONE và merge;
- giữ task nhỏ, reviewable và có acceptance criteria rõ ràng;
- ưu tiên deterministic tests/evals trước live LLM validation;
- bảo vệ secrets và dữ liệu học sinh.

## Workflow scope guardrails

- Roadmap link: [docs/ROADMAP.md](docs/ROADMAP.md).
- Core-loop impact: mỗi thay đổi phải nêu rõ tác động đến core learning loop; nếu không có tác động trực tiếp thì giữ ở mức nhỏ nhất cần thiết.
- Why now: task spec phải giải thích vì sao thay đổi cần thực hiện ở thời điểm hiện tại.
- Why not defer: task spec phải giải thích vì sao không nên trì hoãn thay đổi sang milestone sau.
- Exit criterion affected: task phải chỉ rõ exit criterion nào bị ảnh hưởng và cách kiểm chứng.
- Integration-first rule: ưu tiên tích hợp vào seam hiện có trước khi tạo abstraction hoặc subsystem mới.
- Evidence-before-expansion rule: chỉ mở rộng scope sau khi có evidence từ test, review, hoặc runtime behavior.
- Documentation proportionality: tài liệu phải tương xứng với rủi ro và phạm vi thay đổi; không tạo ceremony thay cho evidence.
- Task eligibility rule: task chỉ nên được thực hiện khi trực tiếp thúc đẩy phase hiện tại của roadmap, đóng integration debt của core loop, sửa regression/blocker đã đo được, đáp ứng acceptance/exit criterion, hoặc được hỗ trợ bởi evidence cụ thể từ eval/product.
- Abstraction gate: không tạo service, adapter, resolver, interface, hoặc shared abstraction mới trừ khi nó loại bỏ logic trùng lặp thực tế, thực thi invariant quan trọng của product/safety, thiết lập typed boundary cần thiết, hoặc bắt buộc bởi nhiều caller hiện tại.
- Module-exit gate: trước khi chuyển sang module hoặc feature family mới, phải kiểm tra core-loop module hiện tại còn material integration debt hay không. Component đã có unit test chưa được coi là fully integrated khi roadmap yêu cầu nó tham gia live product flow.

## 1. Source of truth hierarchy

Khi có xung đột:

```text
1. GitHub/Git repository hiện tại
2. Pull Request hiện tại của task
3. TASK_INDEX.md
4. task file đang ACTIVE
5. 09_DEV_WORKFLOW.md
6. architecture/product-rule documents
7. current-state snapshots or conversation history, only as supplemental context
```

Không suy luận trạng thái dự án chỉ từ snapshot hoặc chat cũ nếu Git/PR/task-control nói khác.

## 2. Responsibility split

### ChatGPT owns

- architecture;
- product/engineering decisions;
- trust-boundary decisions;
- chọn task kế tiếp;
- decomposition thành micro-task;
- task specification;
- acceptance criteria;
- test/eval design;
- Codex handoff prompt;
- Pull Request diff review;
- regression interpretation;
- closure approval;
- documentation decisions;
- task sequencing.

Trước mỗi implementation task, ChatGPT phải xác định:

```text
Goal
Context
Allowed files
Forbidden scope
Acceptance criteria
Tests
Stop conditions
Delivery workflow
```

### Codex owns

- tạo/switch task branch;
- task lifecycle start;
- implementation trong scope đã khóa;
- scoped debugging;
- thêm/sửa tests trong allowed scope;
- chạy focused tests;
- chạy full/integration tests khi môi trường cho phép;
- commit trên task branch;
- push task branch;
- tạo/update Draft Pull Request;
- ghi completion packet vào PR;
- chuyển PR sang Ready for review khi validation xong.

Codex không tự thay đổi architecture hoặc trust boundary.

### Human/user owns

- cấp GitHub access/authentication;
- xử lý environment-specific issues;
- chạy local tests nếu Codex runtime không dùng được;
- merge PR sau khi ChatGPT đã approve closure.

User không cần copy-paste toàn bộ diff giữa Codex và ChatGPT nếu ChatGPT account đang dùng có GitHub access.

## 3. Core workflow

```text
ChatGPT
→ xác định task
→ inspect đúng seam cần thiết
→ khóa task spec
→ tạo Codex handoff hoàn chỉnh

Codex
→ sync main
→ tạo/switch task branch
→ task start
→ xác nhận ACTIVE + CONSISTENT
→ implement đúng allowed scope
→ chạy focused tests
→ chạy full/integration tests
→ git diff --check
→ commit trên task branch
→ push branch
→ mở/update Draft PR
→ ghi completion packet vào PR
→ khi validation xong: mark Ready for review
→ STOP

ChatGPT
→ đọc repo + task file + PR body + complete PR diff
→ review production diff
→ review tests
→ kiểm tra acceptance criteria
→ kiểm tra scope
→ kiểm tra test evidence
→ yêu cầu sửa nếu cần

Codex
→ sửa trên cùng task branch/PR nếu được yêu cầu
→ rerun validation
→ update PR
→ Ready for review lại

ChatGPT
→ nếu đạt: REVIEW_RESULT = APPROVED_FOR_CLOSURE

Codex hoặc user
→ cập nhật task file với validation evidence
→ task done
→ task status
→ review lifecycle
→ push closure metadata lên cùng PR nếu cần

ChatGPT
→ review closure/status lần cuối

User
→ merge PR vào main

GitHub
→ main trở thành source of truth mới

ChatGPT
→ chọn task kế tiếp
```

Nguyên tắc:

```text
ChatGPT specifies and reviews.
Codex implements and validates.
GitHub PR carries the handoff.
Git main records accepted truth.
```

## 4. Branch policy

Mọi implementation task phải chạy trên branch riêng.

Quy ước:

```text
codex/<TASK-ID>
```

Ví dụ:

```text
codex/M05-17
codex/M10-04
codex/M08-10
```

Setup/docs-only work có thể dùng:

```text
chore/<short-name>
```

Codex không được implementation trực tiếp trên `main`.

Trước task:

```powershell
git switch main
git pull --ff-only
git switch -c codex/<TASK-ID>
```

Nếu branch đã tồn tại:

```powershell
git switch codex/<TASK-ID>
```

## 5. Main branch protection

GitHub `main` phải được bảo vệ tối thiểu bằng:

```text
Require a pull request before merging
Block force pushes
Restrict deletions
```

Không push trực tiếp implementation vào `main`.

## 6. Pull Request lifecycle

### Draft PR while Codex is working

PR phải ở Draft cho tới khi:

```text
implementation complete
focused validation complete
full validation complete when required
git diff --check passes
completion packet updated
```

### Ready for review

Chỉ khi các điều kiện trên đạt, Codex:

```text
CHATGPT_REVIEW_READY: true
```

và chuyển Draft PR thành:

```text
Ready for review
```

`Ready for review` là tín hiệu bàn giao chính thức từ Codex sang ChatGPT.

### Merge

Codex không merge.

Merge chỉ sau:

```text
ChatGPT: APPROVED_FOR_CLOSURE
task lifecycle: DONE + CONSISTENT
final closure review complete
```

## 7. Pull Request body contract

PR body tối thiểu:

```markdown
# Task

<TASK-ID> — <name>

## Task contract

`tasks/<MODULE>/<TASK-ID>.md`

## Status

CHATGPT_REVIEW_READY: false

## Files changed

- ...

## Implementation summary

...

## Focused validation

...

## Full validation

...

## Diff check

`git diff --check`: PASS/NOT RUN

## Known risks

...

## Reviewer instructions

Read:
- TASK_INDEX.md
- relevant section of docs/ROADMAP.md
- 09_DEV_WORKFLOW.md
- task file above
- complete PR diff

Do not merge automatically.
```

Khi hoàn tất:

```text
CHATGPT_REVIEW_READY: true
```

## 8. Mandatory review gate

Codex không được self-approve implementation.

Trước:

```text
task done
merge PR
```

ChatGPT phải review tối thiểu:

- production diff;
- test diff;
- focused test result;
- full regression result theo scope;
- PR file list;
- allowed-file compliance;
- forbidden-scope compliance;
- acceptance checklist;
- known risks;
- trust-boundary implications;
- answer-leakage implications khi liên quan Tutor Engine.

Nếu chưa có PR diff review, task chưa ready to close.

Nếu test chưa chạy do environment thiếu runtime/dependency:

- Codex phải báo rõ;
- không được claim PASS;
- user có thể chạy local;
- test evidence local phải được đưa vào PR/task evidence;
- ChatGPT review evidence trước closure.

## 9. Commit policy

Codex được phép commit trước ChatGPT review, nhưng chỉ trên task branch.

Được phép:

```text
commit on codex/<TASK-ID>
push codex/<TASK-ID>
update PR
```

Không được phép:

```text
commit/push implementation directly to main
merge PR
mark task DONE before ChatGPT approval
```

Một task branch có thể có nhiều commit trong quá trình review/fix.

## 10. Task size and scope rules

Mỗi Codex task mặc định:

```text
1 goal
1 small logical change
2–6 files
```

Task phải có:

```text
Goal
Context
Allowed files
Forbidden scope
Implementation requirements
Acceptance criteria
Tests
Stop conditions
Delivery workflow
Return/PR format
```

Codex phải STOP và báo lại nếu:

- cần sửa file ngoài allowed scope;
- cần dependency mới;
- cần thay architecture;
- cần migration/schema ngoài dự kiến;
- cần thay public contract ngoài task;
- task bắt đầu chạm nhiều subsystem;
- acceptance criteria không còn rõ;
- implementation cần phá trust boundary đã khóa.

## 11. Task lifecycle

Repository có task-control workflow:

```text
task status
task start Mxx-yy
task done Mxx-yy
```

Trên Windows/PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ..\dev.ps1 task status
powershell -NoProfile -ExecutionPolicy Bypass -File ..\dev.ps1 task start Mxx-yy
powershell -NoProfile -ExecutionPolicy Bypass -File ..\dev.ps1 task done Mxx-yy
powershell -NoProfile -ExecutionPolicy Bypass -File ..\dev.ps1 review
```

Sau `task start` hoặc `task done`, phải kiểm tra:

```text
ACTIVE: ...
INDEX_STATUS: ...
FILE_STATUS: ...
CONSISTENT: yes
```

Nếu `CONSISTENT: no`, không tiếp tục.

Task file phải có heading chính xác:

```text
## Acceptance checklist
```

`task done` chỉ chạy sau:

```text
ChatGPT REVIEW_RESULT: APPROVED_FOR_CLOSURE
```

## 12. Standard Codex handoff contract

Template:

```text
TASK: <ID> — <name>

Goal:
...

Context:
...

Allowed files:
- ...

Forbidden scope:
- ...

Implementation requirements:
1. ...

Acceptance criteria:
- ...

Tests:
- focused ...
- full ...

Stop conditions:
- ...

DELIVERY WORKFLOW

Repository:
<OWNER>/ai-tutor-vn-plus

Branch:
codex/<TASK-ID>

Base:
main

1. Sync main.
2. Create/switch task branch.
3. Start repository task lifecycle.
4. Confirm ACTIVE + CONSISTENT.
5. Implement only allowed scope.
6. Run focused validation.
7. Run full validation required by task.
8. Run git diff --check and git status.
9. Commit task-scope changes on task branch.
10. Push task branch.
11. Open/update Draft PR to main.
12. Put completion packet in PR body.
13. When implementation and validation are complete:
    - set CHATGPT_REVIEW_READY: true
    - mark PR Ready for review.
14. STOP.

DO NOT:
- merge;
- push directly to main;
- mark task DONE;
- broaden scope.

ChatGPT review is the closure gate.
```

## 13. Codex completion packet

PR body/report nên có:

```text
TASK_STATUS
FILES_CHANGED
IMPLEMENTATION_SUMMARY
TESTS_ADDED
FOCUSED_TEST_RESULT
FULL_TEST_RESULT
DIFF_CHECK
GIT_STATUS
KNOWN_RISKS
```

Task-specific sections có thể thêm khi hữu ích.

Nếu test chưa chạy:

```text
NOT RUN
reason: ...
```

Không được ghi PASS nếu không thực sự chạy.

## 14. ChatGPT review result contract

Nếu có blocker:

```text
REVIEW_RESULT: CHANGES_REQUIRED

BLOCKERS
- ...

REQUIRED_CHANGES
- ...

WHY
- ...

NEXT_CODEX_ACTION
- ...
```

Nếu đạt:

```text
REVIEW_RESULT: APPROVED_FOR_CLOSURE

ACCEPTANCE_STATUS
...

TEST_EVIDENCE
...

SCOPE_CHECK
...

KNOWN_RISKS
...

CLOSURE_ACTION
...
```

## 15. Test strategy

### Tier 1 — Focused deterministic gate

Ví dụ:

```text
unit test đúng module
focused API regression
focused migration test
focused verifier test
```

### Tier 2 — Full deterministic/integration gate

Trước closure:

```text
full backend pytest
frontend lint
frontend production build
offline eval regression
```

tùy scope.

### Tier 3 — Live model gate

Chỉ dùng khi thay đổi ảnh hưởng model/prompt/provider behavior.

Không dùng paid live eval thay deterministic tests.

## 16. Backend validation conventions

Backend venv:

```text
backend\.venv
```

Từ `backend`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q <focused-test>
.\.venv\Scripts\python.exe -m pytest -q
```

Nếu Codex environment không chạy được Python:

```text
Codex implements
→ user runs tests locally
→ evidence được đưa vào PR
→ ChatGPT reviews evidence
```

## 17. Frontend validation conventions

Trên PowerShell dùng:

```powershell
npm.cmd run lint
npm.cmd run build
```

Nếu dependencies chưa materialize và repo không có lockfile:

```powershell
npm.cmd install --no-package-lock
```

Sau đó kiểm tra:

```powershell
git status --short
```

## 18. Git/GitHub validation conventions

Trước Ready for review:

```powershell
git diff --check
git status --short
git diff main...HEAD --stat
```

PR phải trỏ:

```text
base: main
head: codex/<TASK-ID>
```

Windows warning `LF will be replaced by CRLF` không tự động là blocker.

## 19. GitHub CLI conventions

Kiểm tra:

```powershell
gh auth status
```

Không in/copy raw authentication token.

Useful commands:

```powershell
gh repo view
gh pr create
gh pr view
gh pr ready
gh pr status
```

Nếu `gh` không khả dụng trong Codex environment, Codex được phép push branch và user tạo PR thủ công.

## 20. Product/architecture guardrails

Luôn giữ:

- Socratic tutoring trước direct-answer solving;
- không lộ final answer quá sớm;
- deterministic verification là authority khi khả thi;
- model `likely_correct` không tự động trở thành verified correctness;
- generation và verification tách biệt khi có thể;
- mastery update cần trusted evidence;
- student/minor data phải được bảo vệ;
- không thêm dependency nếu chưa giải thích lợi ích;
- modular monolith cho tới khi có bằng chứng cần microservices.

Khi sửa:

```text
API
→ update schema + tests

business logic
→ add unit/regression test

tutor behavior
→ add eval/anti-answer-leakage case khi phù hợp
```

## 21. Trust-boundary rule

Nếu client chỉ chọn `question_id`, server phải resolve trusted server-side item.

Không tin client copies của:

```text
problem_text
expected_answer
verification_family
difficulty
```

Nếu persisted trusted identity không resolve được:

```text
fail closed
```

## 22. Secrets and student-data safety

Không được:

- in API key;
- đưa raw token vào PR;
- commit `.env`;
- log secrets;
- đưa raw student PII vào eval fixture;
- đưa unnecessary minor/student data vào task report;
- copy private data vào public test artifacts.

Repo có thể là public tùy GitHub plan, nên secret hygiene là bắt buộc.

## 23. Conversation/account recovery protocol

ChatGPT account có thể thay đổi.

Không dựa vào memory account cũ.

Khi user nói `tiếp tục`, `continue`, hoặc `resume project`, ChatGPT nên đọc:

```text
1. TASK_INDEX.md
2. 09_DEV_WORKFLOW.md
3. task ACTIVE file, nếu có
4. PR hiện tại của task/branch
5. relevant roadmap/architecture/product docs khi cần
```

Nếu Project files stale so với GitHub:

```text
GitHub/Git thắng
```

### Nếu có ACTIVE task

1. đọc task;
2. đọc PR;
3. kiểm tra `CHATGPT_REVIEW_READY`;
4. nếu false: không review final;
5. nếu true: review complete PR diff + evidence.

### Nếu không có ACTIVE task

1. đọc TASK_INDEX;
2. đọc 09_DEV_WORKFLOW;
3. xác định planned next task từ roadmap khi cần;
4. inspect đúng seam;
5. tạo task spec + Codex handoff.

## 24. Recommended recovery prompt for any ChatGPT account

```text
Tiếp tục AI Tutor VN.

GitHub repository là source of truth.

Đọc:
1. TASK_INDEX.md
2. 09_DEV_WORKFLOW.md
3. task ACTIVE nếu có
4. Pull Request hiện tại của branch
5. relevant roadmap/architecture/product docs nếu cần

Review/continue theo workflow trong repository.

Không dựa vào memory của conversation cũ.
Không task done hoặc merge nếu implementation chưa đạt acceptance.
```

## 25. Current-state snapshot policy

Current-state snapshots, bao gồm `chatgpt_project_pack/08_CURRENT_STATE.md`, chỉ là supplemental starter context và không phải authoritative project state. Snapshot nào stale phải nhường cho GitHub/Git, PR, TASK_INDEX, và ACTIVE task file.

Nếu repository có snapshot:

```markdown
# Current State

Latest merged commit:
`<sha> <message>`

Active task:
`<ID> — <name>` hoặc `none`

Active branch:
`codex/<ID>` hoặc `none`

Active PR:
`#<number>` hoặc `none`

Supplemental context only.
GitHub/Git, current PR, TASK_INDEX, and ACTIVE task file are authoritative.
```

## 26. TASK_INDEX policy

Lifecycle states:

```text
BACKLOG
READY
ACTIVE
BLOCKED
REVIEW
DONE
```

Tối đa một implementation task ACTIVE tại một thời điểm, trừ khi được document rõ.

## 27. Documentation artifact policy

Task file nên lưu:

```text
Goal
Context
Micro-task
Allowed files
Forbidden scope
Acceptance checklist
Validation
Tests
Risks
Codex prompt
Validation evidence sau review
```

Sau ChatGPT approval mới `task done`.

## 28. What NOT to do for speed

Không:

- cho Codex đọc/sửa toàn repo nếu không cần;
- bỏ PR diff review;
- bỏ focused tests;
- bỏ full regression gate khi task yêu cầu;
- push trực tiếp main;
- merge trước ChatGPT approval;
- mark DONE trước ChatGPT approval;
- gom nhiều subsystem vào một task;
- thêm dependency chỉ để tiện;
- đổi architecture trong implementation task;
- dùng live LLM eval thay deterministic tests;
- bỏ trust boundary vì model có thể xử lý;
- sửa unrelated files để working tree sạch;
- tự nhảy task khi task hiện tại chưa đạt acceptance.

## 29. Default workflow after merge

```text
main updated
→ task is DONE
→ update any supplemental current-state snapshot if needed
→ identify next planned task
→ inspect smallest seam
→ create task spec
→ create Codex handoff
→ next codex/<TASK-ID> branch
```

Không reuse branch cũ cho task logic mới.

## 30. Compact protocol summary

```text
GitHub is memory.
Git main is accepted truth.
PR is the Codex → ChatGPT handoff.
ChatGPT specifies and reviews.
Codex implements and validates.
User merges after closure approval.
```

Default sequence:

```text
inspect
→ spec
→ codex/<TASK-ID>
→ ACTIVE
→ implementation
→ focused tests
→ full tests
→ commit branch
→ push
→ Draft PR
→ Ready for review
→ ChatGPT PR review
→ APPROVED_FOR_CLOSURE
→ task DONE
→ merge
→ next task
```

New ChatGPT account:

```text
connect/read GitHub
→ TASK_INDEX
→ DEV_WORKFLOW
→ ACTIVE task
→ active PR
→ continue
```

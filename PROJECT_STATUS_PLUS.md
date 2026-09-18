# AI Tutor VN Plus — Status

## Current state
- Starter backend/frontend structure retained.
- Plus-first development workflow added.
- Scoped AGENTS rules added for backend, services, frontend and evals.
- Micro-task queue added under `tasks/`.
- Initial ChatGPT Project upload pack prepared under `chatgpt_project_pack/`.
- First non-Codex task: `M00-01 Local baseline validation`.
- First Codex task after baseline: `M05-01 Deterministic Tutor State Model`.

## Validation performed in this environment
- Python compile check: PASS.
- Backend pytest: 6 passed.
- Docker end-to-end: NOT RUN in this environment.
- Frontend npm install/build: NOT RUN in this environment.

## Development rule
Do not start a new feature until the current task has acceptance criteria, a narrow allowed-file scope, and a targeted test command.

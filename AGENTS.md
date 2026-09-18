# AGENTS.md — AI Tutor VN

This repository is an education product, not a generic homework-answer bot.

## Product principles
1. Prefer Socratic tutoring over revealing final answers immediately.
2. Every tutoring response should identify the skill being practiced and the next smallest useful step.
3. Student mistakes are learning signals. Store structured misconception tags when possible.
4. Never treat an LLM answer as mathematically verified merely because it is fluent.
5. Keep deterministic verification separate from generation where feasible.
6. Protect minors' data. Avoid collecting data that is not needed for learning.
7. Build the simplest deployable architecture first; do not introduce microservices without a measured need.

## Architecture boundaries
- `api/`: HTTP transport only.
- `services/`: business logic and AI orchestration.
- `models/`: database entities.
- `schemas/`: request/response contracts.
- `core/`: config/security.
- Frontend should never call OpenAI directly; all model access goes through backend.

## Coding rules
- Python: type hints, small functions, explicit errors, pytest for business logic.
- TypeScript: strict mode, no `any` unless justified.
- New endpoints need a schema and at least one test.
- Database migrations should be added before production deployment.
- API keys must remain server-side.

## Definition of done
A feature is done when: implementation + tests + error handling + documentation + observable success/failure path are present.

## Plus / Codex scope discipline
- Treat `TASK_INDEX.md` and `tasks/` as the execution queue.
- Codex should receive one micro-task at a time.
- A normal task changes 2–6 files; broader scope must be justified in the ticket.
- Read only the files named by the ticket plus the nearest applicable `AGENTS.md` files.
- If a required dependency is outside allowed scope, stop and report instead of exploring the repository.
- Use targeted tests first; full integration checks are milestone gates, not every-ticket defaults.

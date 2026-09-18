# Baseline Results

Date: 2026-09-18
Machine / OS: Windows 10 Pro, WindowsVersion 2009, OS build 22621
Docker version: Docker 29.7.2; Docker Compose v5.5.1
Node version (if used outside Docker): N/A - not used outside Docker
Python version (if used outside Docker): N/A - not used outside Docker

## Git provenance
Status: NOT ESTABLISHED

Observed:
- `git status --short` failed because the source snapshot is not a Git repository.
- No `.git` directory was found under `D:\BOT_AI`.
- Current source therefore has no verifiable baseline commit SHA.

Follow-up:
- Establish Git source-of-truth and baseline commit in M00-02.

## Docker build
Status: PASS

Commands:
- `docker --version`
- `docker compose version`
- `docker compose config`
- `docker compose up --build`
- `docker compose ps`

Result:
- `docker compose config`: PASS
- PostgreSQL: UP / healthy
- Backend: UP on port 8000
- Frontend: UP on port 3000

Notes:
- No code, dependency, Dockerfile, or architecture changes were made during baseline validation.

## Backend tests
Status: PASS

Command:
- `docker compose exec backend pytest -q`

Result:
- `6 passed in 0.61s`

## Backend health/docs
Status: PASS

Verified:
- `http://localhost:8000/docs` opened successfully.
- `GET /health` returned HTTP 200.
- Response reported `status=ok`.
- Environment reported `development`.
- AI integration reported `ai_enabled=false`.

## Frontend
Status: PASS

Verified:
- `http://localhost:3000` opened successfully.
- AI Tutor VN MVP UI rendered without an observed startup error or blank page.

## Smoke flow
Status: PASS

Flow exercised:
1. Registration attempt using the existing demo account returned `Email already registered`.
2. Login with the existing account succeeded.
3. Created a Grade 8 student profile successfully.
4. Started a text algebra problem: `2x + 3 = 11`.
5. Tutor session opened successfully.
6. Initial tutor response used a Socratic prompt and did not reveal the final answer.
7. Student submitted the step: subtract 3 from both sides.
8. Tutor responded with a follow-up reasoning prompt and did not reveal the final answer.

Result:
- Auth flow: PASS
- Student profile flow: PASS
- Text problem flow: PASS
- Interactive tutor turn: PASS
- Final-answer leakage observed in tested turn: NO

## Blockers
- No runtime blocker found for Docker boot, backend tests, frontend startup, authentication, student creation, or the tested text tutor flow.
- Git metadata is missing from the current source snapshot; baseline commit provenance must be established in M00-02.
- AI integration currently reports `ai_enabled=false`; API-key enablement remains a Phase 0 follow-up.

## Baseline decision
ESTABLISHED for the current source snapshot.

The local Docker stack boots successfully, backend tests pass, frontend/backend smoke checks pass, and one authenticated interactive text tutor flow completes successfully.

M00-02 must establish the Git source-of-truth, baseline commit, and canonical test commands before implementation work begins.

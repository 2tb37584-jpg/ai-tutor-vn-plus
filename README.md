# AI Tutor VN — Starter Project

A production-oriented starter project for building a Vietnamese AI tutor inspired by the useful parts of Gauth, but designed around **learning**, not answer copying.

## What is included

- Next.js web UI for tutor chat and image upload
- FastAPI backend
- PostgreSQL persistence
- Email/password authentication with JWT
- Student profiles
- Tutor sessions and message history
- Problem analysis from text or image
- Socratic Tutor Engine using OpenAI Responses API
- Structured model outputs with Pydantic
- Basic mastery tracking per skill
- Deterministic math verification helpers using SymPy
- Docker Compose development environment
- Tests for core learning logic
- PRD, architecture, data model, prompts, roadmap and security notes
- `AGENTS.md` for Codex/agentic development

## Product philosophy

The core loop is:

`Problem -> Diagnose -> Ask -> Observe -> Hint -> Check -> Update mastery -> Next problem`

Not:

`Problem -> Reveal answer`

## Quick start

### Requirements
- Docker Desktop / Docker Engine with Compose
- OpenAI API key for real AI responses (the app still starts without one in demo mode)

### 1. Configure

```bash
cp .env.example .env
```

Put your API key in `.env`:

```env
OPENAI_API_KEY=...
```

### 2. Start

```bash
docker compose up --build
```

Open:
- Web: http://localhost:3000
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

### 3. First use

1. Register a user.
2. Create a student profile.
3. Open Tutor.
4. Type a question or upload an image.
5. The tutor analyzes the problem, chooses a skill and starts with a guided question instead of immediately exposing the full answer.

## Development stages

### Stage A — Validate the tutoring loop
Use the current project with 50–100 real exercises. Measure:
- OCR/problem extraction correctness
- tutor helpfulness
- hallucination/error rate
- number of hints before mastery
- student completion rate

### Stage B — Curriculum + adaptive engine
Add curriculum graph, prerequisites, spaced repetition, richer mastery model and question bank.

### Stage C — Productization
Add parent/teacher dashboards, subscriptions, voice, mobile client, moderation, analytics and production observability.

See `docs/ROADMAP.md` for the detailed plan.

## Important limitations of this starter

- The database tables are auto-created at startup for developer convenience; production should use Alembic migrations.
- Auth is intentionally minimal and should be replaced/hardened before public launch.
- Mastery tracking is a transparent heuristic, not a validated psychometric model.
- SymPy verification covers only a subset of mathematics.
- Voice, billing, push notifications and native mobile apps are intentionally deferred.

## Recommended first milestone

Do **not** build every Gauth feature immediately. First prove that the Tutor Engine teaches one narrow segment well, e.g. Vietnamese Grade 8 algebra. Once error rate and learning metrics are acceptable, broaden the curriculum.

## ChatGPT Plus development mode
For quota-efficient development, start with:
1. `CHATGPT_PROJECT_SETUP.md`
2. `CHATGPT_PROJECT_INSTRUCTIONS.md`
3. `TASK_INDEX.md`
4. `tasks/M00_BASELINE/M00-01.md`

Use the files under `chatgpt_project_pack/` as the initial reference upload set for a ChatGPT Project. Keep source code in Git and attach only the relevant module files when reviewing a task.

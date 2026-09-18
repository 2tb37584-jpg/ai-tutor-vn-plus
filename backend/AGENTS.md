# Backend agent rules

Read root `AGENTS.md` first.

- FastAPI routes are transport only; business logic belongs in services.
- Keep model calls behind service boundaries.
- Use typed Pydantic schemas for API and AI structured data.
- Never expose model API keys to frontend.
- Prefer deterministic code for state transitions, scoring and verification.
- Every backend business-logic change needs focused pytest coverage.
- Do not alter database entities unless the ticket explicitly allows it.

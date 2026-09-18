# Codex / vibe-coding workflow

Use this project as a repository, not as one giant chat prompt.

## First session
Ask the coding agent to:
1. Read `AGENTS.md`.
2. Read `README.md`, `docs/PRD.md`, `docs/ARCHITECTURE.md` and `docs/ROADMAP.md`.
3. Run existing tests before editing.
4. Make only the requested milestone changes.
5. Add/update tests and docs with every feature.

## Recommended prompts

### Milestone 1 — Explicit tutor state machine
> Read AGENTS.md and the tutoring docs. Implement an explicit TutorSession state machine with states diagnose, prompt_attempt, hint_1, hint_2, worked_step, verify, transfer_question and review. Keep current API backwards compatible. Add unit tests. Do not add new infrastructure.

### Milestone 2 — Automatic attempt scoring
> Add an application service that converts a tutor turn into a structured attempt event only when confidence is high. Do not blindly use likely_correct from one LLM call. Add a second validation path and tests for ambiguity.

### Milestone 3 — Curriculum graph
> Replace free-form skill tags with a controlled curriculum registry for Grade 8 algebra. Add prerequisites and aliases. Unknown model tags must map to a safe unknown tag rather than creating database skills automatically.

### Milestone 4 — Evaluation runner
> Build a CLI that runs evals/cases.jsonl through problem analysis and first-turn tutoring. Report extraction accuracy, skill-tag match and answer-leakage failures. Save JSON results under evals/results but do not commit API keys or raw student data.

## Rules for accepting agent changes
Never accept a large refactor just because it looks cleaner. Require one of:
- measurable correctness improvement
- reduced latency/cost
- simplified operational burden
- prerequisite for a scheduled product feature

Run tests after each milestone and commit small changes.

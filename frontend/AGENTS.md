# Frontend agent rules

Read root `AGENTS.md` first.

- Frontend calls backend APIs only; never OpenAI directly.
- Optimize first for a clear tutoring conversation, student attempt input and visible learning progress.
- Avoid UI frameworks or state-management libraries unless the ticket requires them.
- Keep TypeScript strict and avoid `any`.
- Do not redesign unrelated pages during a scoped task.

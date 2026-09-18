# Services agent rules

Read root and backend AGENTS files first.

- Services own business logic; they should not depend on HTTP request objects.
- Tutor generation, verification, mastery and curriculum are separate concerns.
- A fluent model response is not evidence of correctness.
- Tutor code must avoid premature final-answer leakage.
- New service outputs should be typed and testable.
- Do not refactor unrelated services during a scoped ticket.

# Task Index

Status values: BACKLOG / READY / ACTIVE / BLOCKED / REVIEW / DONE.

| ID | Module | Task | Status | Codex? |
|---|---|---|---|---|
| M00-01 | Baseline | Run local baseline and capture failures | DONE | No |
| M00-02 | Baseline | Establish baseline commit and test commands | DONE | No |
| M00-03 | Baseline | Establish Alembic migration baseline | DONE | Yes, small |
| M00-04 | Baseline | Adopt existing dev DB into Alembic baseline | DONE | No |
| M00-05 | Baseline | Switch runtime schema workflow to Alembic | DONE | Yes, small |
| M05-01 | Tutor Engine | Define deterministic tutor state model | DONE | Yes, small |
| M05-02 | Tutor Engine | Implement state transition rules | DONE | Yes |
| M05-02A1 | Tutor Engine | Add persisted tutor session state | DONE | Yes, small |
| M05-02A2 | Tutor Engine | Wire persisted state through tutor API | DONE | Yes, small |
| M05-03 | Tutor Engine | Add hint escalation policy | BACKLOG | Yes |
| M05-04 | Tutor Engine | Add answer-leakage guard | BACKLOG | Yes |
| M07-01 | Skill Graph | Define Grade 8 algebra taxonomy | BACKLOG | Mostly ChatGPT |
| M07-02 | Skill Graph | Implement controlled skill registry | BACKLOG | Yes |
| M06-01 | Verifier | Harden one-variable linear equation verifier | BACKLOG | Yes |
| M06-02 | Verifier | Add expression-equivalence verification | BACKLOG | Yes |
| M08-01 | Mastery | Define mastery event contract | BACKLOG | Mostly ChatGPT |
| M08-02 | Mastery | Implement v1 mastery update | BACKLOG | Yes |
| M08-03 | Mastery | Add misconception evidence model | BACKLOG | Yes |
| M09-01 | Evals | Build baseline evaluation runner | BACKLOG | Yes |
| M09-02 | Evals | Add answer-leakage suite | BACKLOG | Yes |
| M10-01 | UI | Tutor conversation shell | BACKLOG | Yes |
| M10-02 | UI | Student attempt + hint controls | BACKLOG | Yes |

## Current recommended sequence
1. M00-01
2. M00-02
3. M05-01
4. M05-02
5. M05-03
6. M05-04
7. M07-01
8. M07-02
9. M06-01
10. M08-01 onward

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
| M05-03 | Tutor Engine | Add state-aware hint generation policy | DONE | Yes |
| M05-04A | Tutor Engine | Hide internal solution data from student API | DONE | Yes, small |
| M05-04B1 | Tutor Engine | Add internal expected-answer storage | DONE | Yes, small |
| M05-04B2 | Tutor Engine | Persist expected answer from tutor start | DONE | Yes, small |
| M05-04B3A | Tutor Engine | Add deterministic answer-leakage detector | DONE | Yes, small |
| M05-04B3B | Tutor Engine | Enforce runtime answer-leakage guard in tutor API | DONE | Yes, small |
| M05-05 | Tutor Engine | Record student reply latency | DONE | Yes |
| M05-06 | Tutor Engine | Add deterministic tutor session summary | DONE | Yes |
| M07-01 | Skill Graph | Define Grade 8 algebra taxonomy | DONE | Mostly ChatGPT |
| M07-02 | Skill Graph | Implement controlled skill registry | DONE | Yes |
| M06-01 | Verifier | Harden one-variable linear equation verifier | DONE | Yes |
| M06-02 | Verifier | Add expression-equivalence verification | DONE | Yes |
| M08-01 | Mastery | Define mastery event contract | DONE | Mostly ChatGPT |
| M08-02 | Mastery | Implement v1 mastery update | DONE | Yes |
| M08-03 | Mastery | Add misconception evidence model | DONE | Yes |
| M09-01 | Evals | Build baseline evaluation runner | DONE | Yes |
| M09-02 | Evals | Add answer-leakage suite | DONE | Yes |
| M09-03 | Evaluation | Expand Grade 8 algebra eval corpus to 20 cases | DONE | Yes |
| M09-04 | Evals | Expand Grade 8 algebra eval corpus to 40 cases | DONE | Yes |
| M09-05 | Evals | Expand Grade 8 algebra eval corpus to 60 cases | DONE | Yes |
| M09-06 | Evals | Expand Grade 8 algebra eval corpus to 80 cases | DONE | Yes |
| M09-07 | Evals | Expand Grade 8 algebra eval corpus to 100 cases | DONE | Yes |
| M09-08 | Evals | Run live model baseline validation | DONE | No |
| M09-08A | Evals | Add OpenAI-compatible provider base URL | DONE | Yes |
| M09-08B | Evals | Add configurable structured API mode | DONE | Yes |
| M09-09 | Evals | Constrain problem-analysis skills to controlled registry | DONE | Yes |
| M09-10 | Evals | Prevent single-symbol leakage false positives | ACTIVE | Yes |
| M09-11 | Evals | Correct over-broad repeated-factor leakage fixture | READY | No |
| M10-01 | UI | Tutor conversation shell | DONE | Yes |
| M10-02A | Tutor Engine | Explicit hint request contract | DONE | Yes |
| M10-02B | UI | Student attempt + hint controls | DONE | Yes |

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

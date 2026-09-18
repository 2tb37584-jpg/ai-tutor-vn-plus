# Development roadmap

## Phase 0 — Setup (1–2 days)
- Run Docker project.
- Add API key.
- Verify text tutor flow.
- Verify image tutor flow.
- Create first 20 Grade 8 algebra eval cases.

Exit: one developer can reproduce the system from a clean machine.

## Phase 1 — Teaching loop (Week 1–2)
- Explicit tutor state machine.
- Better attempt detection from chat.
- Controlled skill taxonomy.
- Misconception tags.
- Record answer/hint latency.
- Add session summary.

Exit: 100 curated problems pass extraction/pedagogy regression checks.

## Phase 2 — Correctness (Week 3–4)
- Add solver adapters by problem family.
- Stronger algebra verifier.
- Numeric/unit verifier.
- Geometry verifier strategy.
- Escalate model when analyzer/verifier disagree.

Exit: >=98% correctness on supported initial domain.

## Phase 3 — Adaptive learning (Week 5–6)
- Curriculum prerequisite graph.
- Question bank.
- Difficulty estimates.
- Spaced repetition scheduler.
- Next-best-question recommendation.
- Replace heuristic mastery with calibrated BKT/IRT only if data is sufficient.

Exit: measurable post-test improvement on pilot users.

## Phase 4 — Parent/teacher experience (Week 7–8)
- Weekly progress dashboard.
- Weak-skill explanations.
- Learning time and hint dependence.
- Assignments and goals.

Exit: non-technical parent can understand what the learner should practice next.

## Phase 5 — Content/RAG (Week 9)
- Ingest approved curriculum/lesson files.
- Retrieval scoped by grade/unit.
- Citation/provenance in teacher-facing view.
- Prompt-injection defenses for documents.

## Phase 6 — Voice/mobile (Week 10–12)
- Realtime voice prototype.
- Mobile-responsive polish or React Native client.
- Camera capture UX.
- Latency and cost tuning.

## Phase 7 — Launch hardening
- Production auth
- observability
- backups
- rate limiting
- moderation/safety
- deletion/export flows
- billing if commercial
- legal/privacy review for target market

## Rule for expansion
Do not add another subject merely because the model can answer it. Add a subject only when taxonomy, evals and verification strategy exist for it.

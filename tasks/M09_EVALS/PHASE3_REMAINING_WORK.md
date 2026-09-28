# Phase 3 Remaining Work Contract

Status: APPROVED PLAN — M09-29 persists this document
Phase: Phase 3 pilot readiness

## Scope and exit boundary

This contract covers the remaining path from deterministic pilot infrastructure to a real pilot capable of producing measurable paired pre/post evidence. It does not claim pilot readiness, measurable improvement, Phase 3 completion, or permission to begin Phase 4.

Required final path:

```text
pilot infrastructure
→ synthetic end-to-end validation
→ operational/privacy readiness
→ real pilot
→ real paired pre/post evidence
→ Phase exit review
```

## Approved architecture decisions

### Pilot identity

Pilot enrollment is server-owned. At enrollment creation the server generates and persists an opaque public pilot identifier and generates a secure opaque random internal `assignment_seed`. M09-30 owns the complete persistence foundation for the enrollment, assignment, and lifecycle state needed by later Phase 3 tasks.

Neither value may be derived from `student_id`, name, email, phone, chat content, or other PII. The seed is server-internal, is never exposed to the client, is not persisted under the current architecture, and is discarded after frozen assignments are created. A future reviewed task may persist it only if a concrete requirement proves that necessary. Standard-library secure/random identity primitives are preferred; no external dependency is required.

### Frozen assignments

At enrollment creation:

```text
assignment_seed
→ assign_pilot_items(...)
→ persist explicit per-skill PRE / learning / POST question IDs
→ discard assignment_seed
```

The public pilot identifier and explicit assignment roles are persisted. The assignment seed is transient and is not a runtime input after enrollment. Runtime must not repeatedly recompute assignments from question-bank ordering.

The persisted pilot enrollment must support, at minimum:

- opaque public pilot identity;
- student ownership/reference;
- lifecycle state for `PRE → INTERVENTION → POST → COMPLETE`;
- created/updated or equivalent minimal lifecycle timestamps.

Each of the nine persisted skill assignments must retain `skill_code`, `pre_question_id`, `learning_question_id`, and `post_question_id`, plus minimal trusted state sufficient to record PRE deterministic result, learning completion, and POST deterministic result. Acceptable state includes result/status and completion/submission timestamps or an equivalent reviewed representation. The exact field names and types remain subject to the M09-30 database/schema checkpoint. Raw assessment answers are not persisted by this contract, and no assignment-seed column is added.

A student may have at most one non-terminal pilot enrollment at a time. M09-31 rejects a new enrollment when one already exists; reset and reenrollment semantics are outside this protocol. Whether database-level uniqueness is also appropriate remains a M09-30 schema-checkpoint decision.

### Assessment boundary

PRE and POST use a dedicated deterministic assessment path and are not ordinary tutor sessions.

Assessment behavior:

- trusted authored items only;
- deterministic verifier is the correctness authority;
- no LLM correctness judgment;
- no hints;
- no mastery update;
- no expected answer in public payload;
- no verifier reference in public payload;
- no answer feedback that can teach the answer;
- no raw learner assessment answer persistence unless a later reviewed requirement proves it necessary.

Persist only the minimal trusted result/state needed for measurement.

### Learning boundary

Pilot intervention must enforce the exact persisted `learning_question_id`. The client cannot substitute another authored question and have it count toward pilot completion. Pilot tutor sessions require server-trusted pilot provenance, while existing tutor-state semantics remain authoritative.

### Generic-path and TRANSFER leakage boundary

For a learner with an active pilot, generic system-controlled authored-question paths must not expose any frozen assignment role:

```text
PRE
LEARNING
POST
```

This applies to generic next-learning recommendation, generic TRANSFER selection, and direct `/tutor/start-authored`. The trusted persisted pilot assignment is the authority. Generic behavior remains unchanged for non-pilot learners.

Inside the exact pilot-provenance learning session, TRANSFER excludes PRE and POST for that skill. The assigned LEARNING item may remain eligible as TRANSFER if necessary. A fourth authored item is not required.

This boundary prevents system-controlled leakage. It does not attempt to block manually typed equivalent/free-text problems, learning outside the product, or fuzzy semantic matches. No LLM-based leakage inference is introduced.

### Phase ordering

Before PRE is complete, pilot learning start is unavailable and generic paths still block the frozen learning item. During intervention, the exact frozen learning item is available only through the pilot-specific start/progression path, while generic paths continue blocking all frozen roles. After intervention, POST becomes available only through the pilot assessment path.

### Intervention completion

For each locked pilot skill:

```text
one exact assigned learning item
→ existing trusted tutor completion path
→ skill intervention complete
```

The intervention is complete only when all nine assigned learning skills are complete. Completion is not based on elapsed time, chat-message count, LLM judgment, or mastery probability threshold. Correctness is not required for counting a completed learning item unless a later reviewed contract changes that rule.

### Measurement boundary

Persisted pilot assessment state projects into the existing `PilotAssessmentRecord` contract. `calculate_pilot_measurement(...)` from M09-22 remains the measurement authority. Reporting must preserve explicit missing-pre, missing-post, invalid/incomplete, unsupported-verification, and indeterminate-verification counts. No real learner PII belongs in measurement artifacts or public repository fixtures.

### Phase exit

Phase 3 remains incomplete after implementation and synthetic tests. Phase exit requires a real pilot, real paired pre/post evidence, truthful disclosure of matched learner count and measured result, and ChatGPT phase-exit review. Do not invent a statistical-significance requirement or unsupported minimum effect-size threshold.

## Ordered workstreams and tasks

### Workstream B — Pilot identity and persistence

#### M09-30 — Persist pilot enrollment, frozen assignments, and lifecycle state

Intent:

- add database model/migration for the complete pilot persistence foundation;
- create opaque pilot identity and server-owned random assignment seed;
- call M09-24 once;
- persist explicit PRE/learning/POST IDs;
- persist lifecycle state for `PRE → INTERVENTION → POST → COMPLETE`;
- reserve minimal trusted PRE result, learning completion, and POST result state without raw assessment-answer persistence;
- reserve a required nullable trusted reference from `TutorSession` to the exact persisted pilot skill assignment, for example `TutorSession → nullable pilot_skill_assignment_id → persisted per-skill pilot assignment`; exact model/column naming is subject to the M09-30 database/schema checkpoint;
- support the single non-terminal-pilot-per-student invariant, with exact enforcement strategy reviewed at the schema checkpoint;
- do not persist `assignment_seed`;
- no API yet.

Mandatory checkpoint: database/schema review.

#### M09-31 — Add owner-authorized pilot enrollment/status API

Intent:

- authenticated owner may enroll an owned student;
- server creates assignment context;
- client never supplies the seed;
- response does not expose seed or future reserved IDs;
- expose only minimal pilot status/progress.

Mandatory checkpoint: public API and authorization review.

### Workstream C — Trusted PRE/POST assessment

#### M09-32 — Add deterministic pilot assessment domain service

Intent:

- next assessment item comes from frozen assignment;
- deterministic verification only;
- no LLM or mastery mutation;
- no raw answer persistence;
- persist trusted verification status;
- use the persisted PRE/POST result state established by M09-30;
- enforce strict PRE-before-learning and POST-after-intervention ordering;
- fail closed for unsupported/indeterminate conditions.

M09-32 must not introduce a new unreviewed persistence model or migration. If the M09-30 schema is insufficient, stop for ChatGPT database/schema review.

#### M09-33 — Add trusted pilot PRE/POST delivery and submission API

Intent:

- expose only the current assessment item;
- do not disclose future POST during PRE or learning;
- expose no expected answer or verifier metadata;
- provide no immediate correctness/solution feedback;
- follow the existing owner/student access boundary;
- validate submitted question identity against the current assignment.

Mandatory checkpoint after Workstream C: assessment trust and public API review.

### Workstream D — Intervention and leakage

#### M09-34A — Add exclusion support to transfer-question selection

Intent:

- extend `get_transfer_question_for_skill(...)` or the smallest existing transfer-selection seam with caller-supplied exclusions;
- preserve generic/default behavior;
- keep pilot semantics out of the generic selector;
- add focused tests proving excluded IDs are never selected.

#### M09-34B — Enforce active-pilot reserved-item guards across generic tutor paths

Intent:

- while a learner has an active pilot intervention, generic next-learning recommendation excludes that learner's persisted frozen PRE, learning, and POST IDs;
- generic TRANSFER selection excludes persisted frozen PRE, learning, and POST IDs;
- `/tutor/start-authored` rejects an authored question ID that is any frozen PRE, learning, or POST ID for that learner's active pilot;
- preserve current behavior for non-pilot learners;
- use trusted persisted pilot assignment state as authority; never trust client-supplied reservation information.

Boundary:

This prevents system-controlled leakage. It does not attempt fuzzy matching or block manually typed equivalent/free-text problem content. No LLM-based leakage inference is introduced.

#### M09-35 — Add exact assigned pilot learning-session start

Intent:

- server selects the next incomplete persisted learning assignment;
- client cannot choose an arbitrary question;
- start an authored tutor session using trusted question-bank content;
- persist the required trusted pilot assignment provenance on `TutorSession`;
- reuse or refactor existing authored-session construction only when justified by two real callers;
- do not duplicate question-bank authority.

#### M09-36 — Track pilot intervention completion and exact progression

Intent:

- when a pilot-provenance tutor session reaches trusted `COMPLETE`, mark that assignment complete;
- return or resolve the next exact assigned learning item;
- generic recommender must not replace pilot-assigned progression;
- after all nine skills complete, pilot becomes POST-eligible;
- record learning completion against the persisted per-skill assignment state established by M09-30;
- do not change generic tutor-state semantics.

M09-36 must not introduce a new unreviewed persistence model or migration. If additional persistence becomes necessary, stop.

Mandatory checkpoint after Workstream D: tutor runtime, leakage, and trust review.

### Workstream E — Measurement

#### M09-37 — Project persisted pilot assessment state into M09-22 measurement records

Intent:

- use opaque pilot identity as measurement pairing identity;
- include no names, email, phone, or raw chats;
- use deterministic projection;
- keep M09-22 as calculator authority;
- map missing, incomplete, unsupported, and indeterminate outcomes explicitly.
- do not create a separate measurement persistence subsystem.

#### M09-38 — Add aggregate pilot measurement report command

Intent:

- provide an operational/internal command or similarly non-public seam;
- query pilot records;
- call the M09-22 projection/calculator;
- output aggregate metrics by default;
- expose no PII or raw assessment responses;
- do not create an unauthenticated cohort analytics API.

Mandatory checkpoint after Workstream E: measurement correctness and privacy review.

### Workstream F — Pilot readiness

#### M09-39 — Add deterministic end-to-end pilot lifecycle regression

Synthetic flow:

```text
enroll
→ frozen assignments
→ complete PRE
→ assigned learning for all nine skills
→ TRANSFER never uses reserved PRE/POST
→ intervention complete
→ complete POST
→ measurement projection
→ M09-22 report
```

No live LLM dependency is required where existing seams can be stubbed or exercised deterministically.

#### M10-05 — Add minimal pilot PRE → learning → POST UI

Intent:

- minimal pilot UX only;
- use trusted backend state;
- keep assignment rules out of the frontend;
- expose no seed, answers, or verifier metadata;
- use the pilot-specific learning start path rather than arbitrary `/start-authored`.

#### M09-40 — Add real-pilot operations/privacy/readiness runbook

The runbook must document:

- supported Grade 8 algebra population;
- PRE → intervention → POST protocol;
- no Phase 3 success claim before real evidence;
- no real pilot data committed to public Git;
- data minimization;
- consent/guardian process explicitly decided before real-minor participation;
- retention/deletion handling explicitly decided before the real pilot;
- synthetic dry-run requirement;
- rollback/support procedure for pilot failures.

Do not claim legal compliance.

Mandatory checkpoint after Workstream F: pilot readiness review.

### Workstream G — Real pilot

#### M09-41 — Execute real pilot and retain aggregate measurement evidence

This is not an autonomous Codex implementation task. It requires human/operational participation and an approved privacy, consent, and retention process. Real learner records must not be committed to Git.

### Workstream H — Phase exit

#### M09-42 — Evaluate Phase 3 exit criterion from real pilot evidence

This is ChatGPT-owned review. Required evidence:

- a real pilot occurred;
- matched valid pre/post records exist;
- an M09-22 report exists;
- matched learner count is disclosed;
- measured pre/post result is disclosed truthfully.

If evidence does not demonstrate post-test improvement, Phase 3 remains active/incomplete and Phase 4 must not begin.

## Autonomy and checkpoint rules

After M09-29 is merged, Codex may execute the approved implementation graph under Phase/Workstream Delegation. It must not bypass these checkpoints:

1. after M09-30 — database/schema;
2. after M09-31 — enrollment API/authorization;
3. after M09-33 — assessment trust/public API;
4. after M09-36 — tutor runtime/leakage/intervention;
5. after M09-38 — measurement/privacy;
6. after M09-40 — real-pilot readiness;
7. M09-42 — Phase exit.

Between checkpoints, autonomous task transition is allowed only when focused tests, required regressions, exact scope, acceptance criteria, and the approved next task all pass without a new architecture, trust, schema, API, persistence, privacy, or dependency decision. Otherwise stop and return to ChatGPT.

## Privacy and non-goals

No real learner names, emails, phone numbers, chats, images, or free-text student content may enter this contract, fixtures, or public Git. Do not implement any task in this document as part of M09-29. Do not start Phase 4.

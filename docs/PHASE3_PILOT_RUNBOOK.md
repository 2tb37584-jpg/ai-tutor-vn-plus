# Phase 3 Pilot Operations, Privacy, and Readiness Runbook

> **M09-40 DONE does NOT authorize M09-41.** No real cohort may begin until a human completes the private readiness packet and ChatGPT completes the mandatory Workstream F readiness review with an explicit GO decision.

This runbook defines the AI Tutor VN project's operational policy for the Phase 3 pilot.

It is not a representation of legal compliance and is not legal advice.

This document defines gates; it does not execute a real pilot, claim pilot readiness, or claim Phase 3 completion.

## 1. Purpose, scope, and supported population

The evidence claim is limited to:

- Grade 8 algebra learners;
- the currently supported deterministic verification domain;
- the locked nine-skill Phase 3 blueprint below.

The pilot does not provide evidence about other grades, other subjects, geometry, or broader populations. The current UI is Vietnamese; operators must ensure every participant can meaningfully use this interface. Results do not establish evidence for other language experiences.

The locked skills are:

1. `arithmetic.signed_number_operations`
2. `algebra.expression.distributive_property`
3. `algebra.expression.combine_like_terms`
4. `algebra.expression.simplify`
5. `algebra.identity.basic`
6. `algebra.linear_equation`
7. `algebra.equation.equivalent_transform`
8. `algebra.factorization`
9. `algebra.rational_expression.domain`

## 2. Human operational roles

Before enrollment, privately assign at least a Pilot owner, Pilot support operator, and Data/privacy owner. One person may hold multiple roles, but responsibilities must be explicit. A private readiness record identifies who owns participant eligibility, consent records, pilot support, incident decisions, data deletion, and measurement execution. Do not commit names or contact details to this public repository.

## 3. Dedicated deployment and clean database — hard gate

The cohort must run in a dedicated pilot deployment/environment with a dedicated real-pilot database. Normally, the mandatory synthetic browser dry-run uses a separate synthetic-only database, never the intended real-pilot database. The synthetic database must never later be reused as the real cohort database; it may be destroyed after the dry-run.

After the final synthetic dry-run passes, independently verify and privately record that the intended real-pilot database contains zero:

- pre-existing `PilotEnrollment` records;
- synthetic/test learner records;
- previous pilot cohort records.

M09-38 currently selects every persisted `PilotEnrollment` and has no cohort filter, date filter, or student filter. Therefore a shared or historical database can contaminate aggregate measurement. Do not work around this in M09-40 by changing M09-38.

This clean-state verification must happen after the final synthetic dry-run and before readiness GO review or any real participant account creation/enrollment. If a clean isolated real-pilot database cannot be provided: **NO-GO; M09-41 must not start.**

If there is a concrete reason to run the synthetic dry-run against the intended real-pilot database, then after the dry-run and before any real account creation/enrollment, destroy and recreate that datastore or use another reviewed complete-reset procedure. The reset must remove all synthetic cohort/application state that could affect the real cohort, not merely delete a `PilotEnrollment` row. Re-run and privately record the full clean-state verification after the reset. If a complete verified reset/recreation cannot be performed: **NO-GO**. The synthetic database must not be repurposed as the real cohort database.

## 4. Deployment and version pinning

Before enrollment, record privately:

- exact deployed Git commit SHA;
- deployment/environment identifier;
- CI run used as release evidence;
- pilot start date.

The deployed build must correspond to reviewed `main`. Do not run a real cohort from an unreviewed branch.

## 5. Required technical preflight

Before real enrollment, all must be true, in this order:

- M09-39 is DONE;
- M10-05 is DONE and its UI is merged;
- this M09-40 runbook is approved;
- current `main` CI is green;
- pilot deployment uses the reviewed `main` commit;
- final synthetic browser dry-run has passed using a separate synthetic-only database, or the intended pilot datastore has undergone the complete reviewed reset/recreation fallback;
- after that final dry-run (and fallback reset, if used), the real-pilot database has been independently verified clean and isolated as defined above;
- readiness GO review is complete;
- required secrets are configured, and secret values are not copied into this runbook or evidence.

For the preferred path the gate order is: reviewed release deployed → synthetic browser dry-run using the separate synthetic-only database → dry-run PASS → real-pilot database clean-state verification → readiness GO review → only then real participant account creation/enrollment.

For the fallback path the order is: dry-run on intended real-pilot database → complete datastore reset/recreation → clean-state verification → readiness GO review → real enrollment.

M09-39 synthetic deterministic E2E is backend lifecycle evidence. M10-05 is UI integration evidence. Neither substitutes for the manual synthetic browser dry-run below.

## 6. Consent, guardian consent, and learner assent

Consent is an operational prerequisite outside the product. Before account creation or pilot enrollment:

- a minor requires **guardian consent AND learner assent**;
- an adult requires **participant consent**.

Never enroll first and collect consent afterward. Store consent records outside the application database and public Git, in an access-controlled private operational location. Use a private, non-identifying participant code to link operational records.

The minimum private consent register contains:

- participant code;
- minor/adult status;
- consent/assent obtained: yes/no;
- date;
- consent-form/version identifier;
- withdrawal status/date, if applicable.

Do not collect government IDs or unrelated sensitive information merely for this pilot. Missing or uncertain consent/assent means **NO-GO for that participant**. This is project policy, not a legal-compliance claim.

## 7. Data minimization and participant instructions

Use only learner-level data needed to operate the pilot. Where operationally possible, use pseudonymous display names, avoid real names in student profile fields, and avoid unnecessary real contact data in the pilot application. Contact/consent linkage belongs only in the private operator register.

During the measured pilot:

- do not use image upload;
- do not ask learners to paste personal information;
- do not ask for school name, phone, address, health information, IDs, or similar details.

PRE/POST use authored assessment items only. Assessment raw candidate answers are not persisted by the current assessment backend. However, intervention `TutorMessage` content **is persisted**. Tell participants not to enter identifying or sensitive personal information in tutoring replies.

Do not export raw chats, screenshots containing learner information, uploaded images, raw answers, account/contact data, or per-learner exports into task docs, GitHub issues, PRs, public Git, or measurement artifacts.

## 8. Public repository rule

**No real learner data enters the public Git repository.** This includes names, emails, phone numbers, participant/guardian contact information, consent records, raw tutor messages, screenshots, assessment candidates, database dumps, per-learner exports, and real pilot public IDs. Repository examples and tests remain synthetic only.

## 9. Retention, withdrawal, and deletion

Internal project retention policy: learner-level pilot data may be retained only during the active pilot and while M09-42 Phase 3 exit review or pilot-incident resolution remains pending.

After M09-42 concludes, delete learner-level pilot data from the dedicated pilot environment as soon as operationally verified and no later than **30 calendar days after the M09-42 decision**. Do not retain learner-level data indefinitely.

When a participant withdraws, stop further collection immediately, exclude them from further pilot participation, and delete their learner-level pilot data as soon as operationally verified and no later than **30 calendar days after withdrawal**.

If deletion cannot be safely performed using available operational controls, the pilot is **NOT ready to begin**. M09-40 adds no deletion API. Prefer destruction of the dedicated pilot environment/database after the cohort is complete and M09-42 no longer requires learner-level debugging evidence.

## 10. Backup and log retention

Before the real pilot, the human operator must privately document:

- whether database backups exist;
- whether application/platform logs contain learner-level content;
- backup/log retention duration;
- who can access backups/logs;
- how expiration/deletion is verified.

Confirm the infrastructure retention path is compatible with the 30-day project retention policy. If provider-managed backup retention cannot satisfy it, surface this to ChatGPT readiness review before M09-41. Do not claim deleted data is gone from backups unless that has been verified.

## 11. Aggregate evidence retention

M09-38 output is aggregate-only but can still be sensitive for a tiny known cohort. Store real aggregate pilot evidence in a private access-controlled project location, not public Git. Retain only what M09-41/M09-42 require:

- matched learner count;
- mean PRE score;
- mean POST score;
- mean paired delta;
- median paired delta;
- improved/unchanged/declined counts;
- M09-22 exclusion counts;
- exact deployed commit;
- report-generation date/run reference.

Do not retain per-learner measurement records as the official evidence artifact. External/public release of tiny-cohort aggregates requires a separate privacy review. Do not invent suppression thresholds here.

## 12. Measurement authority and never-started roster limitation

Run `python -m app.services.pilot_measurement_report` from the reviewed backend deployment/environment. M09-37 remains projection authority; M09-22 remains measurement authority; M09-38 remains report authority. The primary metric remains `mean paired_delta`.

Do not recalculate scores in a spreadsheet, manually drop inconvenient learners, invent significance tests or minimum effect-size gates, or change denominator rules.

A learner/enrollment with no PRE and no POST record projects no measurement record. Thus M09-22/M09-38 cannot by themselves count an entirely never-started enrollment as both missing PRE and missing POST. Maintain a private operational cohort roster/count so M09-41 evidence can truthfully disclose authorized/enrolled participant count, never-started count, matched learner count, and reported exclusions. The private roster may contain only minimum operational linkage and must never be committed to Git. Never use it to rewrite M09-22 output.

## 13. Locked pilot protocol

Participant flow:

`consent/assent verified → account/student created → pilot explicitly enrolled → PRE → INTERVENTION → POST → COMPLETE`

### PRE

Nine server-selected authored assessment items. Deterministic verifier is the correctness authority. No hints, mastery update, correctness feedback, or solution feedback.

### INTERVENTION

Nine exact persisted learning assignments, one per locked skill. Start only through `/tutor/start-pilot-learning/{student_id}`. Generic `/start-authored` is not pilot authority. Completion remains trusted tutor-runtime completion.

### POST

POST is available only after all nine learning assignments complete. Apply the same assessment trust rules as PRE.

### COMPLETE

Completion means protocol completion only. It does not mean the learner improved, the pilot succeeded, or Phase 3 passed.

## 14. Retryable assessment outcomes

For normal retryable `unsupported` or `indeterminate` outcomes, the UI provides no correctness feedback and the current item remains retryable. Ask the learner to retry the same current item with a clear mathematical response. Do not tell them the correct answer, manually mark correct/incorrect, edit database status, or skip to the next item.

If the same item repeatedly cannot be deterministically scored, pause that participant, record a minimal incident, and escalate for technical review. Do not improvise scoring.

## 15. Mandatory synthetic browser dry-run

Before each real cohort, run one complete synthetic pilot on the exact reviewed release candidate/deployment, using the same reviewed release commit/build, relevant runtime configuration, and application code intended for the real cohort, but a **separate synthetic-only dry-run database**. Never reuse that dry-run database as the real cohort database. Exercise the visible UI through:

`no pilot → explicit enrollment → all PRE items → intervention → all nine pilot learning sessions → POST → COMPLETE`

Verify at minimum:

- no auto-enrollment;
- no assessment correctness feedback;
- no expected answer or verifier metadata shown;
- pilot learning starts through the pilot-specific action;
- generic `/start-authored` is not used as pilot authority;
- selected-student switching does not cross-wire pilot state;
- all nine learning items progress;
- POST appears only after intervention completion;
- COMPLETE wording is neutral.

After completion, run the real aggregate-report command against the synthetic isolated database and verify it succeeds with synthetic-only evidence. Then verify the intended real-pilot database is still independently clean, after this final dry-run. If the intended real-pilot database was used for the dry-run, perform the complete reviewed reset/recreation fallback first and then repeat clean-state verification. Do not define a complete reset as deleting a single `PilotEnrollment` row manually. If synthetic state remains or complete reset cannot be verified: **NO-GO**. If this browser dry-run fails: **NO-GO; do not enroll real participants.** M09-40 defines the gate; it does not execute or claim the dry-run has passed.

## 16. Incident and rollback policy

### Privacy, trust, or correctness-integrity incident

Examples include answer leakage, wrong participant/student state shown, frozen PRE/POST item exposed through tutoring, verifier authority bypass, inconsistent assignment provenance, unexpected learner-data exposure, or database cohort contamination.

If synthetic/test pilot state is discovered in the intended real-pilot database before the first real enrollment, the decision is **NO-GO**; do not create real participant accounts or enroll anyone. If discovered after real enrollment begins, treat it as a database cohort-contamination incident: immediately stop new enrollment, pause the cohort, do not run or continue measurement, and require ChatGPT readiness re-review. Do not manually repair learner phase/status, edit assessment results, or continue measurement. Capture only minimal incident metadata: time, deployment commit, phase, non-identifying participant code if needed, and generic failure description. Do not copy raw chat, answers, or PII into GitHub.

Resume only after a reviewed fix, required regressions passing, the full synthetic browser dry-run passing again, and ChatGPT readiness re-review.

### Ordinary UI/infrastructure failure

Pause the affected session. It may resume from server-owned state only if persisted state is confirmed intact. If state integrity is uncertain, stop; do not manually advance phase. Escalate for review.

## 17. No ad-hoc reset or re-enrollment

The current protocol defines no operator-driven reset semantics. Operators must not manually reset phase, edit assignment rows, replace frozen IDs, delete/recreate rows to make progress, or create another active enrollment as an incident workaround.

If a cohort needs restart/re-enrollment semantics, stop and create a separately reviewed task/decision.

## 18. Support procedure

Before pilot start, provide participants/guardians a private support route; do not put its contact details in the public repository. Support operators should request only a participant code, approximate time, visible phase, and brief problem description.

Do not request passwords, API keys, full chat transcripts, raw assessment responses, or unnecessary screenshots containing PII. Escalate trust/privacy incidents immediately to the pilot/data owner.

## 19. Private GO/NO-GO readiness packet

A human must complete a private readiness record and ChatGPT must review its evidence before any real pilot. Keep the completed record and all private contact/consent details outside public Git. Every mandatory checkbox must be checked; any unchecked mandatory item means **NO-GO**.

```text
[ ] supported population confirmed
[ ] pilot owner assigned
[ ] support operator assigned
[ ] data/privacy owner assigned

[ ] consent process finalized
[ ] guardian consent process finalized for minors
[ ] learner-assent process finalized for minors
[ ] private consent register location/access confirmed

[ ] exact deployment commit recorded
[ ] reviewed main deployed
[ ] CI green
[ ] dedicated pilot environment confirmed
[ ] synthetic dry-run data store is separate from the real cohort database OR the intended pilot datastore was fully reset/recreated after dry-run
[ ] real cohort database was verified clean AFTER the final synthetic dry-run (and after any fallback reset/recreation)
[ ] backup/log retention confirmed
[ ] deletion mechanism confirmed

[ ] M09-39 regression evidence current
[ ] M10-05 UI merged
[ ] full synthetic browser dry-run PASS on exact release
[ ] synthetic aggregate report command PASS

[ ] incident/rollback owner available
[ ] private support route available
[ ] no unresolved privacy/trust blocker
[ ] no unresolved correctness/integrity blocker
```

M09-40 DONE does **not** itself authorize M09-41. After this documentation closes, the human fills the readiness packet, then ChatGPT performs the mandatory Workstream F pilot-readiness review. Only an explicit GO decision may allow M09-41. Codex cannot make that GO decision.

## 20. Phase boundary

- M09-41 is real pilot execution.
- M09-42 is Phase 3 exit review.

Even after a real pilot, Phase 3 remains incomplete until M09-42. Phase 4 must not begin unless real evidence demonstrates measurable post-test improvement under the locked M09-22 contract and ChatGPT approves the Phase exit.

## 21. Readiness state

This runbook is a policy artifact only. It does not mean the operational roles, dedicated environment/database, consent process, backup/log controls, deletion mechanism, synthetic dry-run, private readiness packet, or ChatGPT GO review have been completed. No real pilot has been run or authorized by this document.

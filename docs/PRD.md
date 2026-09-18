# Product Requirements Document — AI Tutor VN

## 1. Product goal
Build a Vietnamese AI tutor that helps students learn how to solve problems, not merely obtain final answers.

Initial wedge: **Grade 8 algebra**. The architecture supports other grades and subjects, but quality should be proven on one narrow curriculum before expansion.

## 2. Target users
### Student
- Sends a text/image exercise.
- Receives one next-step question or hint.
- Explains reasoning.
- Gets corrective feedback.
- Sees progress over time.

### Parent
- Creates/manages student profiles.
- Reviews progress and weak skills.
- Should see learning indicators, not private verbatim conversations by default without a clear policy.

### Teacher/tutor (later)
- Assigns skill sets and practice.
- Reviews class-level misconceptions.
- Curates problems and explanations.

## 3. Core problem
Homework solvers optimize for answer speed. Learning requires diagnosis, productive struggle, feedback, repetition and transfer.

The product differentiator is the student model:
- skill mastery
- prerequisite gaps
- misconception history
- hint dependence
- recency/forgetting

## 4. MVP user journey
1. Account registration.
2. Create student profile and grade.
3. Enter or photograph an exercise.
4. AI extracts/normalizes the problem.
5. AI tags skills and prerequisites.
6. Tutor asks a focused diagnostic question.
7. Student responds.
8. Tutor gives a hint/correction, not a full answer by default.
9. An attempt is scored.
10. Mastery estimate updates.
11. System recommends the next exercise (Phase 2).

## 5. Functional requirements
### P0
- Auth
- Multiple student profiles
- Text question input
- Image question input
- Structured problem analysis
- Socratic chat
- Session persistence
- Skill tags
- Attempt logging
- Mastery score
- API docs
- Basic error handling

### P1
- Curriculum graph
- Question bank
- Adaptive next-question selection
- Spaced repetition
- Parent dashboard
- Teacher dashboard
- PDF lesson ingestion / retrieval
- Better deterministic verifiers
- Evaluation dashboard

### P2
- Realtime voice tutor
- Native mobile apps
- Whiteboard handwriting
- Billing/subscriptions
- Push notifications
- Classroom workflows

## 6. Explicit non-goals for MVP
- General-purpose chatbot
- Automatic completion of an entire worksheet
- Microservices
- Custom ML mastery model before enough data exists
- Fine-tuning before prompt + evaluation baseline exists

## 7. Success metrics
### Learning quality
- Problem extraction accuracy >= 98% on clean photos, measured on an internal labeled set.
- Skill-tag precision >= 90% on the initial Grade 8 algebra taxonomy.
- Final-answer leakage in first tutor turn < 2%.
- Mathematical correctness >= 98% on supported verified problem classes.
- Student can solve a near-transfer question after tutoring: target +20 percentage points over baseline.

### Product
- Session completion rate
- Median student turns per solved problem
- Hint count distribution
- 7-day returning learners
- Cost per completed learning session
- p50/p95 response latency

## 8. Primary risks
1. Fluent but incorrect explanations.
2. OCR/vision reads the problem incorrectly.
3. Tutor reveals answers too early.
4. Mastery score creates false precision.
5. Student dependence on hints.
6. Cost/latency grows with long chat history.
7. Child/minor privacy and consent obligations.

## 9. Mitigations
- Separate generation from verification.
- Confidence scores and explicit ambiguity handling.
- Prompt/eval tests for answer leakage.
- Keep mastery model transparent until validated.
- Truncate/compact conversation history.
- Minimize stored personal data and establish retention/deletion policy.

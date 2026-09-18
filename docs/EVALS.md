# Evaluation plan

AI tutoring quality must be measured before feature breadth.

## Golden dataset
Create `evals/cases.jsonl` with at least 200 initial cases from the target curriculum.

Each case should contain:
```json
{
  "id": "g8-algebra-001",
  "problem": "2x + 3 = 11",
  "expected_normalized_problem": "2x + 3 = 11; solve for x",
  "expected_skills": ["algebra.linear_equation"],
  "expected_answer": "4",
  "first_turn_must_not_contain": ["x = 4", "đáp án là 4"],
  "risk_tags": []
}
```

## Evaluations
### Extraction
- exact important-number match
- equation match
- diagram/entity match
- confidence calibration

### Pedagogy
- no final-answer leakage in early turns
- asks one question at a time
- hint is relevant to current skill
- language appropriate to grade
- responds constructively to errors

### Correctness
- expected final answer
- algebraic equivalence
- solution-set equivalence
- independent second-solver agreement for supported classes

### Learning
Run pre-test → tutoring → near-transfer post-test.
The core product metric is learning gain, not answer acceptance/thumbs-up alone.

## Release gate
Do not broaden to a new curriculum unit until:
- extraction and math correctness meet threshold
- no severe answer leakage regression
- evaluation set includes adversarial/poor-photo cases

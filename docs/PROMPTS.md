# Tutor prompting protocol

## Principle
Prompts are part of the product specification and must be evaluated like code.

## Problem analyzer
Input: text and/or image.
Output must contain:
- normalized problem
- subject
- grade band
- stable skill tags
- prerequisite tags
- expected answer (internal)
- ambiguity/verification notes
- confidence

Failure behavior:
- Never fill in unreadable numbers.
- Lower confidence for cropped diagrams or missing choices.
- Request a clearer photo when required.

## Tutor turn state machine
Recommended states:
1. `diagnose`
2. `prompt_attempt`
3. `hint_1`
4. `hint_2`
5. `worked_step`
6. `student_explains`
7. `verify`
8. `transfer_question`
9. `review`

Do not let the LLM decide all state transitions implicitly forever. Phase 2 should introduce an explicit state machine in application code.

## Reveal policy
A final answer may be revealed when:
- student has completed the key reasoning; or
- session is explicitly in review mode; or
- repeated attempts indicate the worked example is pedagogically preferable.

Even then, require a follow-up transfer question to distinguish recognition from mastery.

## Misconception taxonomy
Prefer controlled tags:
- `sign_error`
- `distributive_property_error`
- `forgot_domain_condition`
- `fraction_common_denominator_error`
- `formula_recall_gap`
- `diagram_misread`

Free-text misconception descriptions can be stored separately for analysis, but the dashboard should aggregate controlled tags.

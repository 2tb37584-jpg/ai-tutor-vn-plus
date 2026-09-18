# AI Tutor VN — Project Map

## Product thesis
AI Tutor VN phải tối ưu cho `learning gain`, không tối ưu cho `answer speed`.

## Core loop
Problem intake → Problem analysis → Tutor state machine → Student attempt → Verification → Misconception detection → Mastery update → Next learning action.

## Modules
- M00 Baseline & development discipline
- M01 Auth & account boundary
- M02 Student profile
- M03 Problem intake
- M04 Problem analyzer
- M05 Tutor engine
- M06 Math verifier
- M07 Curriculum / skill graph
- M08 Mastery & misconception
- M09 Evaluation
- M10 Tutor UI
- M11 Analytics / parent dashboard
- M12 Voice / camera / advanced input (later)

## Product order
M00 → M05 → M07 → M06 → M08 → M09 → M10 → M11 → M12.

Auth, student profile and problem intake already have starter implementations; stabilize them only when they block the core learning loop.

## Architectural rule
Start as a modular monolith. Modules communicate through typed application contracts. Split services only after measured scale, reliability or ownership pressure justifies it.

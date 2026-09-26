"""Deterministic authored-item assignments for the Phase 3 pilot."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.services.question_bank import get_questions_for_skill


_PILOT_SKILL_CODES = (
    "arithmetic.signed_number_operations",
    "algebra.expression.distributive_property",
    "algebra.expression.combine_like_terms",
    "algebra.expression.simplify",
    "algebra.identity.basic",
    "algebra.linear_equation",
    "algebra.equation.equivalent_transform",
    "algebra.factorization",
    "algebra.rational_expression.domain",
)


@dataclass(frozen=True)
class PilotSkillAssignment:
    skill_code: str
    pre_question_id: str
    learning_question_id: str
    post_question_id: str


def assign_pilot_items(
    *,
    assignment_seed: str,
) -> tuple[PilotSkillAssignment, ...]:
    if not isinstance(assignment_seed, str) or assignment_seed == "":
        raise ValueError("assignment_seed must be a non-empty string")

    assignments: list[PilotSkillAssignment] = []
    for skill_code in _PILOT_SKILL_CODES:
        skill_questions = get_questions_for_skill(skill_code)
        if len(skill_questions) < 3:
            raise ValueError(
                f"Pilot assessment assignment requires at least 3 questions for {skill_code}"
            )

        payload = f"{assignment_seed}\x1f{skill_code}".encode("utf-8")
        digest = hashlib.sha256(payload).digest()
        offset = int.from_bytes(
            digest,
            byteorder="big",
            signed=False,
        ) % len(skill_questions)

        pre = skill_questions[offset]
        learning = skill_questions[(offset + 1) % len(skill_questions)]
        post = skill_questions[(offset + 2) % len(skill_questions)]
        question_ids = (pre.id, learning.id, post.id)
        if len(set(question_ids)) != 3:
            raise ValueError(
                f"Pilot assessment assignment selected duplicate questions for {skill_code}"
            )

        assignments.append(
            PilotSkillAssignment(
                skill_code=skill_code,
                pre_question_id=pre.id,
                learning_question_id=learning.id,
                post_question_id=post.id,
            )
        )

    return tuple(assignments)

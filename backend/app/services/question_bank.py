"""Immutable Grade 8 algebra question bank."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.skill_registry import get_controlled_skills, is_mastery_bearing_skill
from app.services.verifier import (
    ExpressionEquivalenceRequest,
    LinearEquationRequest,
    NumericVerificationRequest,
    ProblemFamily,
    VerificationRequest,
    VerificationStatus,
    verify,
)


_QUESTION_BANK_PATH = Path(__file__).resolve().parents[1] / "data" / "grade8_algebra_question_bank_v1.json"
_REQUIRED_FIELDS = {
    "id",
    "skill_code",
    "problem_text",
    "verification_reference",
    "expected_answer",
    "verification_family",
}
_SUPPORTED_FAMILIES = {
    "numeric",
    "expression_equivalence",
    "linear_equation",
}
_EXPECTED_FAMILY_COUNTS = {family: 4 for family in _SUPPORTED_FAMILIES}


@dataclass(frozen=True)
class QuestionBankItem:
    id: str
    skill_code: str
    problem_text: str
    verification_reference: str
    expected_answer: str
    verification_family: str


def _verification_request(item: QuestionBankItem) -> VerificationRequest:
    family = ProblemFamily(item.verification_family)
    if family is ProblemFamily.NUMERIC:
        return NumericVerificationRequest(
            family=family,
            expected=item.verification_reference,
            candidate=item.expected_answer,
        )
    if family is ProblemFamily.EXPRESSION_EQUIVALENCE:
        return ExpressionEquivalenceRequest(
            family=family,
            left=item.verification_reference,
            right=item.expected_answer,
        )
    return LinearEquationRequest(
        family=family,
        equation=item.verification_reference,
        candidate=item.expected_answer,
    )


def _build_question_bank(records: Any) -> tuple[QuestionBankItem, ...]:
    if not isinstance(records, list) or len(records) != 12:
        raise ValueError("Question bank must contain exactly 12 records")

    definitions = {skill.code: skill for skill in get_controlled_skills()}
    items: list[QuestionBankItem] = []
    ids: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != _REQUIRED_FIELDS:
            raise ValueError("Question bank record has invalid fields")
        if any(not isinstance(value, str) or not value.strip() for value in record.values()):
            raise ValueError("Question bank fields must be non-empty strings")

        question_id = record["id"]
        if question_id in ids:
            raise ValueError(f"Duplicate question id: {question_id}")
        ids.add(question_id)

        skill_code = record["skill_code"]
        definition = definitions.get(skill_code)
        if definition is None or not is_mastery_bearing_skill(skill_code):
            raise ValueError(f"Question has invalid skill code: {skill_code}")

        verification_family = record["verification_family"]
        if verification_family not in _SUPPORTED_FAMILIES:
            raise ValueError(f"Question has unsupported verification family: {verification_family}")
        if definition.verifier_family != verification_family:
            raise ValueError("Question skill and verification family do not match")

        item = QuestionBankItem(**record)
        if verify(_verification_request(item)).status is not VerificationStatus.CORRECT:
            raise ValueError(f"Question verification pair is invalid: {question_id}")
        items.append(item)

    if Counter(item.verification_family for item in items) != _EXPECTED_FAMILY_COUNTS:
        raise ValueError("Question bank has invalid verification family distribution")
    return tuple(items)


with _QUESTION_BANK_PATH.open(encoding="utf-8") as question_bank_file:
    _QUESTION_BANK = _build_question_bank(json.load(question_bank_file))


def get_all_questions() -> tuple[QuestionBankItem, ...]:
    return _QUESTION_BANK


def get_question(question_id: str) -> QuestionBankItem | None:
    return next((item for item in _QUESTION_BANK if item.id == question_id), None)


def get_questions_for_skill(skill_code: str) -> tuple[QuestionBankItem, ...]:
    return tuple(item for item in _QUESTION_BANK if item.skill_code == skill_code)

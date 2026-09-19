from dataclasses import replace

import pytest

from app.services.misconception_evidence import (
    MisconceptionEvidence,
    MisconceptionEvidenceSource,
    MisconceptionEvidenceStatus,
    get_misconceptions_for_skill,
    is_controlled_misconception,
    validate_misconception_evidence,
)
from app.services.skill_registry import get_controlled_skills


LINEAR_MISCONCEPTIONS = (
    "incorrect_variable_isolation",
    "equation_sign_transfer_error",
)


def evidence(**changes: object) -> MisconceptionEvidence:
    base = MisconceptionEvidence(
        student_id=1,
        session_id=2,
        skill_code="algebra.linear_equation",
        misconception_code="incorrect_variable_isolation",
        status=MisconceptionEvidenceStatus.SUSPECTED,
        source=MisconceptionEvidenceSource.DETERMINISTIC_RULE,
        confidence=0.8,
    )
    return replace(base, **changes)


def test_controlled_misconception_lookup_resolves_canonical_and_alias() -> None:
    assert get_misconceptions_for_skill("algebra.linear_equation") == LINEAR_MISCONCEPTIONS
    assert get_misconceptions_for_skill("LINEAR EQUATION") == LINEAR_MISCONCEPTIONS


def test_unknown_and_reserved_skills_have_no_misconceptions() -> None:
    assert get_misconceptions_for_skill("invented.skill") == ()
    assert get_misconceptions_for_skill("general.problem_solving") == ()


def test_each_skill_returns_unique_misconception_codes() -> None:
    for skill in get_controlled_skills():
        misconceptions = get_misconceptions_for_skill(skill.code)
        assert len(misconceptions) == len(set(misconceptions))


def test_misconception_identity_is_skill_specific() -> None:
    assert is_controlled_misconception(
        "algebra.linear_equation",
        "incorrect_variable_isolation",
    )
    assert not is_controlled_misconception(
        "algebra.expression.distributive_property",
        "incorrect_variable_isolation",
    )
    assert not is_controlled_misconception("algebra.linear_equation", "invented_misconception")


@pytest.mark.parametrize(
    "accepted_evidence",
    [
        evidence(),
        evidence(status=MisconceptionEvidenceStatus.CONFIRMED),
        evidence(source=MisconceptionEvidenceSource.LLM_JUDGMENT),
        evidence(source=MisconceptionEvidenceSource.CLIENT_CLAIM),
    ],
)
def test_allowed_source_status_pairs_are_accepted(
    accepted_evidence: MisconceptionEvidence,
) -> None:
    decision = validate_misconception_evidence(accepted_evidence)

    assert decision.accepted is True
    assert decision.reason == "accepted"
    assert decision.skill_code == "algebra.linear_equation"
    assert decision.misconception_code == "incorrect_variable_isolation"


@pytest.mark.parametrize(
    ("rejected_evidence", "reason"),
    [
        (
            evidence(
                source=MisconceptionEvidenceSource.LLM_JUDGMENT,
                status=MisconceptionEvidenceStatus.CONFIRMED,
            ),
            "llm_cannot_confirm_misconception",
        ),
        (
            evidence(
                source=MisconceptionEvidenceSource.LLM_JUDGMENT,
                status=MisconceptionEvidenceStatus.CONFIRMED,
                confidence=1.0,
            ),
            "llm_cannot_confirm_misconception",
        ),
        (
            evidence(
                source=MisconceptionEvidenceSource.CLIENT_CLAIM,
                status=MisconceptionEvidenceStatus.CONFIRMED,
                confidence=1.0,
            ),
            "client_cannot_confirm_misconception",
        ),
        (evidence(confidence=-0.1), "invalid_confidence"),
        (evidence(confidence=1.1), "invalid_confidence"),
        (evidence(student_id=0), "invalid_student_id"),
        (evidence(skill_code="invented.skill"), "skill_not_controlled"),
        (evidence(skill_code="general.problem_solving"), "skill_not_controlled"),
        (
            evidence(misconception_code="distribution_sign_error"),
            "misconception_not_controlled_for_skill",
        ),
    ],
)
def test_rejected_evidence_has_stable_reason(
    rejected_evidence: MisconceptionEvidence,
    reason: str,
) -> None:
    decision = validate_misconception_evidence(rejected_evidence)

    assert decision.accepted is False
    assert decision.reason == reason


def test_accepted_alias_evidence_returns_canonical_skill() -> None:
    decision = validate_misconception_evidence(evidence(skill_code="LINEAR EQUATION"))

    assert decision.accepted is True
    assert decision.skill_code == "algebra.linear_equation"


def test_repeated_lookup_and_validation_do_not_mutate_registry() -> None:
    before = get_controlled_skills()

    for _ in range(3):
        assert get_misconceptions_for_skill("LINEAR EQUATION") == LINEAR_MISCONCEPTIONS
        assert validate_misconception_evidence(evidence()).accepted is True

    assert get_controlled_skills() is before

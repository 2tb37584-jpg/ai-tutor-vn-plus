from dataclasses import replace

import pytest

from app.models import Mastery
from app.services.mastery import (
    MasteryEvidenceEvent,
    MasteryEvidenceType,
    MasteryOutcome,
    VerificationStatus,
    record_mastery_evidence,
    update_probability,
)


class FakeDatabase:
    def __init__(self, mastery: Mastery | None = None) -> None:
        self.mastery = mastery
        self.added: list[object] = []
        self.scalar_calls = 0
        self.flush_calls = 0

    def scalar(self, _statement: object) -> Mastery | None:
        self.scalar_calls += 1
        return self.mastery

    def add(self, record: object) -> None:
        self.added.append(record)
        if isinstance(record, Mastery):
            self.mastery = record

    def flush(self) -> None:
        self.flush_calls += 1


def evidence(**changes: object) -> MasteryEvidenceEvent:
    base = MasteryEvidenceEvent(
        student_id=1,
        session_id=2,
        skill_code="algebra.linear_equation",
        outcome=MasteryOutcome.CORRECT,
        evidence_type=MasteryEvidenceType.DETERMINISTIC_VERIFICATION,
        verification_status=VerificationStatus.VERIFIED,
        verification_method="linear_equation_v1",
    )
    return replace(base, **changes)


def test_correct_increases_mastery_without_many_hints() -> None:
    assert update_probability(0.4, True, 0) > 0.4


def test_wrong_decreases_mastery() -> None:
    assert update_probability(0.7, False, 0) < 0.7


def test_many_hints_reduce_learning_credit() -> None:
    assert update_probability(0.4, True, 5) < update_probability(0.4, True, 0)


@pytest.mark.parametrize(
    "event",
    [
        evidence(),
        evidence(outcome=MasteryOutcome.INCORRECT),
        evidence(evidence_type=MasteryEvidenceType.VERIFIED_TRANSFER, is_transfer=True),
        evidence(
            outcome=MasteryOutcome.INCORRECT,
            evidence_type=MasteryEvidenceType.VERIFIED_TRANSFER,
            is_transfer=True,
        ),
    ],
)
def test_eligible_verified_evidence_is_applied(event: MasteryEvidenceEvent) -> None:
    db = FakeDatabase()

    result = record_mastery_evidence(db, event)

    assert result.applied is True
    assert result.reason == "mastery_updated"
    assert result.skill_code == "algebra.linear_equation"
    assert result.old == 0.35
    assert result.new is not None
    assert db.scalar_calls == 1
    assert db.flush_calls == 1
    assert db.mastery is not None
    assert db.mastery.exposures == 1


@pytest.mark.parametrize(
    ("event", "reason"),
    [
        (evidence(evidence_type=MasteryEvidenceType.CLIENT_CLAIM), "client_claim_not_mastery_eligible"),
        (evidence(evidence_type=MasteryEvidenceType.LLM_JUDGMENT), "evidence_type_not_mastery_eligible"),
        (
            evidence(evidence_type=MasteryEvidenceType.CONFIRMED_MISCONCEPTION),
            "evidence_type_not_mastery_eligible",
        ),
        (evidence(verification_status=VerificationStatus.UNVERIFIED), "verification_not_verified"),
        (evidence(verification_status=VerificationStatus.UNSUPPORTED), "verification_not_verified"),
        (evidence(verification_status=VerificationStatus.DISPUTED), "verification_not_verified"),
        (evidence(outcome=MasteryOutcome.UNKNOWN), "outcome_not_mastery_eligible"),
        (evidence(skill_code="invented.skill"), "skill_not_mastery_eligible"),
        (evidence(skill_code="general.problem_solving"), "skill_not_mastery_eligible"),
        (evidence(hint_count=-1), "invalid_hint_count"),
        (evidence(confidence=-0.1), "invalid_confidence"),
        (evidence(confidence=1.1), "invalid_confidence"),
        (evidence(student_id=0), "invalid_student_id"),
    ],
)
def test_ineligible_evidence_does_not_touch_persistence(
    event: MasteryEvidenceEvent,
    reason: str,
) -> None:
    db = FakeDatabase()

    result = record_mastery_evidence(db, event)

    assert result.applied is False
    assert result.reason == reason
    assert result.old is None
    assert result.new is None
    assert db.scalar_calls == 0
    assert db.flush_calls == 0
    assert db.added == []


def test_confidence_does_not_make_client_claim_eligible() -> None:
    result = record_mastery_evidence(
        FakeDatabase(),
        evidence(evidence_type=MasteryEvidenceType.CLIENT_CLAIM, confidence=1.0),
    )

    assert result.applied is False


def test_reviewed_alias_is_persisted_under_canonical_code() -> None:
    db = FakeDatabase()

    result = record_mastery_evidence(db, evidence(skill_code="LINEAR EQUATION"))

    assert result.applied is True
    assert result.skill_code == "algebra.linear_equation"
    assert db.mastery is not None
    assert db.mastery.skill_code == "algebra.linear_equation"


def test_eligible_correct_increments_exposure_and_streak() -> None:
    mastery = Mastery(
        student_id=1,
        skill_code="algebra.linear_equation",
        probability=0.4,
        exposures=2,
        correct_streak=1,
    )
    db = FakeDatabase(mastery)

    record_mastery_evidence(db, evidence())

    assert mastery.exposures == 3
    assert mastery.correct_streak == 2
    assert mastery.probability > 0.4
    assert mastery.last_seen_at is not None


def test_eligible_incorrect_resets_streak() -> None:
    mastery = Mastery(
        student_id=1,
        skill_code="algebra.linear_equation",
        probability=0.7,
        exposures=4,
        correct_streak=3,
    )
    db = FakeDatabase(mastery)

    record_mastery_evidence(db, evidence(outcome=MasteryOutcome.INCORRECT))

    assert mastery.exposures == 5
    assert mastery.correct_streak == 0
    assert mastery.probability < 0.7

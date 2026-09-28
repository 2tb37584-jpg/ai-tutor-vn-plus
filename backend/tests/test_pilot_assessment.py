from dataclasses import replace
from datetime import datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.entities import (
    Attempt,
    Mastery,
    PilotEnrollment,
    PilotSkillAssignment,
    Student,
    TutorMessage,
    User,
)
from app.services import pilot_assessment
from app.services.question_bank import get_question
from app.services.verifier import VerificationResult, VerificationStatus


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    user = User(email="synthetic@example.com", password_hash="hash")
    session.add(user)
    session.flush()
    session.add(Student(id=1, owner_id=user.id, display_name="Synthetic", grade=8))
    session.commit()
    yield session
    session.close()


def enrollment_fixture(db: Session, *, phase: str = "pre") -> PilotEnrollment:
    enrollment = PilotEnrollment(public_id=f"pilot-{phase}", student_id=1, phase=phase)
    db.add(enrollment)
    db.flush()
    db.add(
        PilotSkillAssignment(
            pilot_enrollment_id=enrollment.id,
            skill_code="algebra.factorization",
            pre_question_id="g8alg.factorization.001",
            learning_question_id="g8alg.factorization.002",
            post_question_id="g8alg.factorization.003",
        )
    )
    db.flush()
    return enrollment


def assignment_for(db: Session, enrollment: PilotEnrollment) -> PilotSkillAssignment:
    assignment = db.scalar(
        select(PilotSkillAssignment).where(
            PilotSkillAssignment.pilot_enrollment_id == enrollment.id
        )
    )
    assert assignment is not None
    return assignment


def test_pre_item_uses_exact_persisted_pre_role_and_safe_fields(db: Session) -> None:
    enrollment = enrollment_fixture(db)

    item = pilot_assessment.get_current_pilot_assessment_item(
        db, enrollment_id=enrollment.id
    )

    assert item is not None
    assert item.phase == "pre"
    assert item.question_id == "g8alg.factorization.001"
    assert item.skill_code == "algebra.factorization"
    assert item.problem_text
    question = get_question("g8alg.factorization.001")
    assert question is not None
    assert item.difficulty == question.difficulty
    assert set(item.__dataclass_fields__) == {
        "phase", "question_id", "skill_code", "problem_text", "difficulty"
    }
    assert not hasattr(item, "expected_answer")
    assert not hasattr(item, "verification_reference")
    assert not hasattr(item, "verification_family")


@pytest.mark.parametrize(
    ("status", "accepted"),
    [
        (VerificationStatus.CORRECT, True),
        (VerificationStatus.INCORRECT, True),
        (VerificationStatus.UNSUPPORTED, False),
        (VerificationStatus.INDETERMINATE, False),
    ],
)
def test_submission_persists_deterministic_status_and_progression(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    status: VerificationStatus,
    accepted: bool,
) -> None:
    enrollment = enrollment_fixture(db)
    monkeypatch.setattr(
        pilot_assessment,
        "verify",
        lambda request: VerificationResult(status),
    )
    now = datetime(2026, 1, 1)

    result = pilot_assessment.submit_pilot_assessment_response(
        db,
        enrollment_id=enrollment.id,
        question_id="g8alg.factorization.001",
        candidate="not-used-by-mocked-verifier",
        now=now,
    )

    assignment = assignment_for(db, enrollment)
    assert result.verification_status is status
    assert result.accepted is accepted
    assert assignment.pre_verification_status == status.value
    assert (assignment.pre_submitted_at == now) is accepted
    assert enrollment.phase == ("intervention" if accepted else "pre")
    assert result.phase_complete is accepted


def test_real_authored_question_and_verifier_are_used(db: Session) -> None:
    enrollment = enrollment_fixture(db)

    result = pilot_assessment.submit_pilot_assessment_response(
        db,
        enrollment_id=enrollment.id,
        question_id="g8alg.factorization.001",
        candidate="(x-3)*(x+3)",
        now=datetime(2026, 1, 1),
    )

    assert result.verification_status is VerificationStatus.CORRECT
    assert result.accepted is True


def test_unsupported_retry_can_succeed_and_same_item_remains_current(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enrollment = enrollment_fixture(db)
    responses = iter(
        (
            VerificationResult(VerificationStatus.UNSUPPORTED),
            VerificationResult(VerificationStatus.CORRECT),
        )
    )
    monkeypatch.setattr(pilot_assessment, "verify", lambda request: next(responses))

    first = pilot_assessment.submit_pilot_assessment_response(
        db, enrollment_id=enrollment.id, question_id="g8alg.factorization.001", candidate="x", now=datetime(2026, 1, 1)
    )
    assert first.accepted is False
    assert pilot_assessment.get_current_pilot_assessment_item(db, enrollment_id=enrollment.id).question_id == "g8alg.factorization.001"

    second = pilot_assessment.submit_pilot_assessment_response(
        db, enrollment_id=enrollment.id, question_id="g8alg.factorization.001", candidate="x", now=datetime(2026, 1, 2)
    )
    assert second.accepted is True
    assert enrollment.phase == "intervention"


@pytest.mark.parametrize("question_id", ["g8alg.factorization.002", "g8alg.factorization.003", "g8alg.identity-basic.001"])
def test_non_current_question_is_rejected_without_mutation(
    db: Session,
    question_id: str,
) -> None:
    enrollment = enrollment_fixture(db)

    with pytest.raises(pilot_assessment.PilotAssessmentQuestionMismatch):
        pilot_assessment.submit_pilot_assessment_response(
            db, enrollment_id=enrollment.id, question_id=question_id, candidate="x", now=datetime(2026, 1, 1)
        )

    assignment = assignment_for(db, enrollment)
    assert assignment.pre_verification_status is None
    assert assignment.pre_submitted_at is None
    assert enrollment.phase == "pre"


def test_pre_completion_exposes_no_item_and_submission_is_unavailable(db: Session) -> None:
    enrollment = enrollment_fixture(db)
    assignment = assignment_for(db, enrollment)
    assignment.pre_verification_status = "correct"
    assignment.pre_submitted_at = datetime(2026, 1, 1)
    enrollment.phase = "intervention"
    db.flush()

    assert pilot_assessment.get_current_pilot_assessment_item(db, enrollment_id=enrollment.id) is None
    with pytest.raises(pilot_assessment.PilotAssessmentUnavailable):
        pilot_assessment.submit_pilot_assessment_response(
            db, enrollment_id=enrollment.id, question_id="g8alg.factorization.001", candidate="x", now=datetime(2026, 1, 2)
        )


def test_post_requires_persisted_post_phase_and_learning_completion(db: Session) -> None:
    enrollment = enrollment_fixture(db, phase="pre")
    with pytest.raises(pilot_assessment.PilotAssessmentStateError):
        enrollment.phase = "post"
        db.flush()
        pilot_assessment.get_current_pilot_assessment_item(db, enrollment_id=enrollment.id)


def test_post_uses_exact_post_role_and_final_submission_completes(db: Session) -> None:
    enrollment = enrollment_fixture(db, phase="post")
    assignment = assignment_for(db, enrollment)
    assignment.pre_verification_status = "incorrect"
    assignment.pre_submitted_at = datetime(2026, 1, 1)
    assignment.learning_completed_at = datetime(2026, 1, 2)
    db.flush()

    item = pilot_assessment.get_current_pilot_assessment_item(db, enrollment_id=enrollment.id)
    assert item is not None
    assert item.question_id == "g8alg.factorization.003"
    result = pilot_assessment.submit_pilot_assessment_response(
        db,
        enrollment_id=enrollment.id,
        question_id=item.question_id,
        candidate="(2*x+1)*(x+3)",
        now=datetime(2026, 1, 3),
    )
    assert result.verification_status is VerificationStatus.CORRECT
    assert result.phase_complete is True
    assert result.enrollment_phase == "complete"
    assert enrollment.phase == "complete"


def test_complete_enrollment_exposes_no_item(db: Session) -> None:
    enrollment = enrollment_fixture(db, phase="complete")
    assignment = assignment_for(db, enrollment)
    assignment.pre_verification_status = "correct"
    assignment.pre_submitted_at = datetime(2026, 1, 1)
    assignment.learning_completed_at = datetime(2026, 1, 2)
    assignment.post_verification_status = "correct"
    assignment.post_submitted_at = datetime(2026, 1, 3)
    assert pilot_assessment.get_current_pilot_assessment_item(db, enrollment_id=enrollment.id) is None


def test_missing_enrollment_is_explicit(db: Session) -> None:
    with pytest.raises(pilot_assessment.PilotAssessmentNotFound):
        pilot_assessment.get_current_pilot_assessment_item(db, enrollment_id=999)


def test_missing_or_mismatched_authored_question_fails_closed(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enrollment = enrollment_fixture(db)
    monkeypatch.setattr(pilot_assessment, "get_question", lambda question_id: None)
    with pytest.raises(pilot_assessment.PilotAssessmentConfigurationError):
        pilot_assessment.get_current_pilot_assessment_item(db, enrollment_id=enrollment.id)

    question = get_question("g8alg.factorization.001")
    assert question is not None
    monkeypatch.setattr(
        pilot_assessment,
        "get_question",
        lambda question_id: replace(question, skill_code="algebra.identity.basic"),
    )
    with pytest.raises(pilot_assessment.PilotAssessmentConfigurationError):
        pilot_assessment.get_current_pilot_assessment_item(db, enrollment_id=enrollment.id)


def test_submission_has_no_raw_answer_or_side_effect_records_and_no_commit(
    db: Session,
) -> None:
    enrollment = enrollment_fixture(db)
    result = pilot_assessment.submit_pilot_assessment_response(
        db,
        enrollment_id=enrollment.id,
        question_id="g8alg.factorization.001",
        candidate="(x-3)*(x+3)",
        now=datetime(2026, 1, 1),
    )
    assert result.accepted is True
    assert db.in_transaction()
    assert db.scalars(select(TutorMessage)).all() == []
    assert db.scalars(select(Attempt)).all() == []
    assert db.scalars(select(Mastery)).all() == []
    assert "(x-3)*(x+3)" not in str(assignment_for(db, enrollment).__dict__)
    assert not hasattr(pilot_assessment, "assign_pilot_items")
    assert not hasattr(pilot_assessment, "TutorAI")


def _complete_pre_and_learning(assignment: PilotSkillAssignment) -> None:
    assignment.pre_verification_status = "correct"
    assignment.pre_submitted_at = datetime(2026, 1, 1)
    assignment.learning_completed_at = datetime(2026, 1, 2)


def _two_assignment_enrollment(db: Session, *, phase: str) -> PilotEnrollment:
    enrollment = enrollment_fixture(db, phase=phase)
    db.add(
        PilotSkillAssignment(
            pilot_enrollment_id=enrollment.id,
            skill_code="algebra.identity.basic",
            pre_question_id="g8alg.identity-basic.001",
            learning_question_id="g8alg.identity-basic.002",
            post_question_id="g8alg.identity-basic.003",
        )
    )
    db.flush()
    return enrollment


def test_intervention_with_incomplete_pre_fails_closed(db: Session) -> None:
    enrollment = enrollment_fixture(db, phase="intervention")
    with pytest.raises(pilot_assessment.PilotAssessmentStateError):
        pilot_assessment.get_current_pilot_assessment_item(db, enrollment_id=enrollment.id)


def test_intervention_with_post_state_fails_closed(db: Session) -> None:
    enrollment = enrollment_fixture(db, phase="intervention")
    assignment = assignment_for(db, enrollment)
    assignment.pre_verification_status = "correct"
    assignment.pre_submitted_at = datetime(2026, 1, 1)
    assignment.post_verification_status = "unsupported"
    with pytest.raises(pilot_assessment.PilotAssessmentStateError):
        pilot_assessment.get_current_pilot_assessment_item(db, enrollment_id=enrollment.id)


def test_pre_with_learning_completion_fails_closed(db: Session) -> None:
    enrollment = enrollment_fixture(db)
    assignment = assignment_for(db, enrollment)
    assignment.learning_completed_at = datetime(2026, 1, 1)
    with pytest.raises(pilot_assessment.PilotAssessmentStateError):
        pilot_assessment.get_current_pilot_assessment_item(db, enrollment_id=enrollment.id)


def test_pre_with_post_state_fails_closed(db: Session) -> None:
    enrollment = enrollment_fixture(db)
    assignment = assignment_for(db, enrollment)
    assignment.post_verification_status = "correct"
    assignment.post_submitted_at = datetime(2026, 1, 1)
    with pytest.raises(pilot_assessment.PilotAssessmentStateError):
        pilot_assessment.get_current_pilot_assessment_item(db, enrollment_id=enrollment.id)


def test_complete_with_incomplete_post_fails_closed(db: Session) -> None:
    enrollment = enrollment_fixture(db, phase="complete")
    assignment = assignment_for(db, enrollment)
    _complete_pre_and_learning(assignment)
    with pytest.raises(pilot_assessment.PilotAssessmentStateError):
        pilot_assessment.get_current_pilot_assessment_item(db, enrollment_id=enrollment.id)


def test_out_of_order_pre_state_fails_closed(db: Session) -> None:
    enrollment = _two_assignment_enrollment(db, phase="pre")
    second = db.scalars(
        select(PilotSkillAssignment)
        .where(PilotSkillAssignment.pilot_enrollment_id == enrollment.id)
        .order_by(PilotSkillAssignment.id)
    ).all()[1]
    second.pre_verification_status = "correct"
    second.pre_submitted_at = datetime(2026, 1, 1)
    with pytest.raises(pilot_assessment.PilotAssessmentStateError):
        pilot_assessment.get_current_pilot_assessment_item(db, enrollment_id=enrollment.id)


def test_out_of_order_post_state_fails_closed(db: Session) -> None:
    enrollment = _two_assignment_enrollment(db, phase="post")
    assignments = db.scalars(
        select(PilotSkillAssignment)
        .where(PilotSkillAssignment.pilot_enrollment_id == enrollment.id)
        .order_by(PilotSkillAssignment.id)
    ).all()
    for assignment in assignments:
        _complete_pre_and_learning(assignment)
    assignments[1].post_verification_status = "correct"
    assignments[1].post_submitted_at = datetime(2026, 1, 3)
    with pytest.raises(pilot_assessment.PilotAssessmentStateError):
        pilot_assessment.get_current_pilot_assessment_item(db, enrollment_id=enrollment.id)


def test_current_unsupported_pre_remains_retryable(db: Session) -> None:
    enrollment = enrollment_fixture(db)
    assignment = assignment_for(db, enrollment)
    assignment.pre_verification_status = "unsupported"
    item = pilot_assessment.get_current_pilot_assessment_item(db, enrollment_id=enrollment.id)
    assert item is not None
    assert item.question_id == assignment.pre_question_id


def test_current_indeterminate_post_remains_retryable(db: Session) -> None:
    enrollment = enrollment_fixture(db, phase="post")
    assignment = assignment_for(db, enrollment)
    _complete_pre_and_learning(assignment)
    assignment.post_verification_status = "indeterminate"
    item = pilot_assessment.get_current_pilot_assessment_item(db, enrollment_id=enrollment.id)
    assert item is not None
    assert item.question_id == assignment.post_question_id

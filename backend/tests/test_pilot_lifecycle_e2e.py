from datetime import datetime, timedelta
import json

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.entities import (
    PilotEnrollment,
    PilotSkillAssignment,
    Student,
    TutorMessage,
    TutorSession,
    User,
)
from app.schemas.tutor import TutorReplyRequest, TutorState, TutorTurn
from app.services import (
    pilot_assessment,
    pilot_enrollment,
    pilot_measurement,
    pilot_measurement_projection,
    pilot_measurement_report,
)
from app.services.question_bank import get_question
from app.services.verifier import VerificationStatus


_PUBLIC_ID = "opaque-m09-39-synthetic-learner"
_ASSIGNMENT_SEED = "pilot-seed-a"
_STARTED_AT = datetime(2026, 9, 1, 9, 0, 0)
_BLUEPRINT_SKILLS = (
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


class DeterministicTutorAI:
    """Provides safe tutor text/state requests without judging correctness."""

    def first_turn(self, _analysis, _grade: int) -> TutorTurn:
        return TutorTurn(
            message="Hãy thử giải thích bước đầu tiên.",
            state=TutorState.VERIFY,
        )

    def continue_turn(self, **_kwargs) -> TutorTurn:
        # Deliberately disagrees with correct answers; the real verifier owns state.
        return TutorTurn(
            message="Em hãy kiểm tra lại lập luận của mình.",
            state=TutorState.COMPLETE,
            likely_correct=False,
        )


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    owner = User(email="m09-39-synthetic@example.test", password_hash="synthetic")
    session.add(owner)
    session.flush()
    student = Student(
        owner_id=owner.id,
        display_name="Synthetic pilot learner",
        grade=8,
    )
    session.add(student)
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _assignment_snapshot(
    assignments: list[PilotSkillAssignment],
) -> tuple[tuple[str, str, str, str], ...]:
    return tuple(
        (
            row.skill_code,
            row.pre_question_id,
            row.learning_question_id,
            row.post_question_id,
        )
        for row in assignments
    )


def _row_count(db: Session, model: type) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def test_complete_synthetic_pilot_lifecycle_uses_real_deterministic_authorities(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pilot_enrollment, "_generate_public_id", lambda: _PUBLIC_ID)
    monkeypatch.setattr(
        pilot_enrollment,
        "_generate_assignment_seed",
        lambda: _ASSIGNMENT_SEED,
    )

    owner = db.scalar(select(User))
    student = db.scalar(select(Student))
    assert owner is not None and student is not None

    # Real enrollment and assignment service; only opaque identity/seed sources are fixed.
    enrollment = pilot_enrollment.create_pilot_enrollment(db, student_id=student.id)
    assignments = list(
        db.scalars(
            select(PilotSkillAssignment)
            .where(PilotSkillAssignment.pilot_enrollment_id == enrollment.id)
            .order_by(PilotSkillAssignment.id)
        ).all()
    )
    assert len(assignments) == 9
    frozen_snapshot = _assignment_snapshot(assignments)
    assert tuple(row[0] for row in frozen_snapshot) == _BLUEPRINT_SKILLS
    assert len({row[0] for row in frozen_snapshot}) == 9
    for _, pre_id, learning_id, post_id in frozen_snapshot:
        assert len({pre_id, learning_id, post_id}) == 3

    expected_answers: set[str] = set()

    # Real PRE domain flow: the current persisted item and authored answer are used.
    tutor_sessions_before_pre = _row_count(db, TutorSession)
    tutor_messages_before_pre = _row_count(db, TutorMessage)
    for index, assignment in enumerate(assignments):
        current = pilot_assessment.get_current_pilot_assessment_item(
            db,
            enrollment_id=enrollment.id,
        )
        assert current is not None
        assert current.phase == "pre"
        assert current.question_id == assignment.pre_question_id
        question = get_question(current.question_id)
        assert question is not None and question.skill_code == assignment.skill_code
        expected_answers.add(question.expected_answer)
        result = pilot_assessment.submit_pilot_assessment_response(
            db,
            enrollment_id=enrollment.id,
            question_id=current.question_id,
            candidate=question.expected_answer,
            now=_STARTED_AT + timedelta(minutes=index),
        )
        assert result.verification_status is VerificationStatus.CORRECT
        assert result.accepted is True
    assert enrollment.phase == "intervention"
    assert _row_count(db, TutorSession) == tutor_sessions_before_pre
    assert _row_count(db, TutorMessage) == tutor_messages_before_pre

    # Only the tutor text/turn adapter, server clock and unrelated mastery side effect
    # are stubbed. Selection, bank, verification, progression and recommendation path
    # remain the production implementations.
    from app.api import tutor as tutor_api

    monkeypatch.setattr(tutor_api, "ai", DeterministicTutorAI())
    monkeypatch.setattr(tutor_api, "_utcnow", lambda: _STARTED_AT)
    monkeypatch.setattr(
        tutor_api,
        "record_mastery_evidence",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        tutor_api,
        "recommend_next_learning_question",
        lambda *_args, **_kwargs: pytest.fail(
            "pilot progression must not invoke the generic recommender"
        ),
    )

    all_pre_ids = {row.pre_question_id for row in assignments}
    all_post_ids = {row.post_question_id for row in assignments}
    all_reserved_ids = all_pre_ids | all_post_ids
    all_question_ids = {
        question_id
        for row in assignments
        for question_id in (
            row.pre_question_id,
            row.learning_question_id,
            row.post_question_id,
        )
    }
    for index, assignment in enumerate(assignments):
        started = tutor_api.start_pilot_learning_tutor(
            student_id=student.id,
            user=owner,
            db=db,
        )
        learning_id = assignment.learning_question_id
        assert started.question.question_id == learning_id
        assert started.question.skill_code == assignment.skill_code
        tutor_session = db.get(TutorSession, started.session_id)
        assert tutor_session is not None
        assert tutor_session.pilot_skill_assignment_id == assignment.id
        assert tutor_session.authored_question_id == learning_id
        assert tutor_session.primary_skill == assignment.skill_code

        learning_item = get_question(learning_id)
        assert learning_item is not None
        expected_answers.add(learning_item.expected_answer)

        entered_transfer = tutor_api.tutor_reply(
            TutorReplyRequest(
                session_id=started.session_id,
                student_message=learning_item.expected_answer,
            ),
            user=owner,
            db=db,
        )
        assert entered_transfer.tutor.state is TutorState.TRANSFER
        transfer_id = tutor_session.transfer_question_id
        assert transfer_id is not None
        assert transfer_id not in all_reserved_ids
        transfer_item = get_question(transfer_id)
        assert transfer_item is not None
        assert transfer_item.skill_code == assignment.skill_code
        expected_answers.add(transfer_item.expected_answer)

        completed = tutor_api.tutor_reply(
            TutorReplyRequest(
                session_id=started.session_id,
                student_message=transfer_item.expected_answer,
            ),
            user=owner,
            db=db,
        )
        assert completed.tutor.state is TutorState.COMPLETE
        assert tutor_session.current_state == TutorState.COMPLETE.value
        assert assignment.learning_completed_at == _STARTED_AT
        if index < len(assignments) - 1:
            assert completed.next_learning_action is not None
            assert (
                completed.next_learning_action.question_id
                == assignments[index + 1].learning_question_id
            )
        else:
            assert completed.next_learning_action is None
            assert enrollment.phase == "post"

    # PRE/POST assessment calls must not create chat/session artifacts.
    tutor_sessions_before_post = _row_count(db, TutorSession)
    tutor_messages_before_post = _row_count(db, TutorMessage)
    for index, assignment in enumerate(assignments):
        current = pilot_assessment.get_current_pilot_assessment_item(
            db,
            enrollment_id=enrollment.id,
        )
        assert current is not None
        assert current.phase == "post"
        assert current.question_id == assignment.post_question_id
        question = get_question(current.question_id)
        assert question is not None and question.skill_code == assignment.skill_code
        expected_answers.add(question.expected_answer)
        result = pilot_assessment.submit_pilot_assessment_response(
            db,
            enrollment_id=enrollment.id,
            question_id=current.question_id,
            candidate=question.expected_answer,
            now=_STARTED_AT + timedelta(days=1, minutes=index),
        )
        assert result.verification_status is VerificationStatus.CORRECT
        assert result.accepted is True
    assert enrollment.phase == "complete"
    assert _row_count(db, TutorSession) == tutor_sessions_before_post
    assert _row_count(db, TutorMessage) == tutor_messages_before_post

    # Frozen PRE/LEARNING/POST identities survive the entire lifecycle unchanged.
    enrollment_id = enrollment.id
    db.expire_all()
    persisted_assignments = list(
        db.scalars(
            select(PilotSkillAssignment)
            .where(PilotSkillAssignment.pilot_enrollment_id == enrollment_id)
            .order_by(PilotSkillAssignment.id)
        ).all()
    )
    assert _assignment_snapshot(persisted_assignments) == frozen_snapshot

    # Real M09-37 projection preserves the opaque pairing identity and PRE/POST order.
    records = pilot_measurement_projection.project_pilot_assessment_records(
        db,
        enrollment_id=enrollment_id,
    )
    assert [record.phase for record in records] == ["pre", "post"]
    assert all(record.learner_id == _PUBLIC_ID for record in records)
    assert all(record.outcome == "valid" for record in records)
    assert all(record.verified_correct_items == 9 for record in records)
    assert all(record.valid_scored_items == 9 for record in records)

    # Real M09-22 calculator: equal synthetic scores are deliberately zero change.
    measurement = pilot_measurement.calculate_pilot_measurement(records)
    assert measurement.matched_learner_count == 1
    assert measurement.mean_pre_score == 1.0
    assert measurement.mean_post_score == 1.0
    assert measurement.mean_paired_delta == 0.0
    assert measurement.median_paired_delta == 0.0
    assert measurement.improved_count == 0
    assert measurement.unchanged_count == 1
    assert measurement.declined_count == 0
    assert measurement.missing_pre == 0
    assert measurement.missing_post == 0
    assert measurement.invalid_incomplete == 0
    assert measurement.unsupported_verification == 0
    assert measurement.indeterminate_verification == 0

    # Real M09-38 report and serializer expose aggregate metrics only.
    aggregate = pilot_measurement_report.build_aggregate_pilot_measurement_report(db)
    serialized = pilot_measurement_report.serialize_aggregate_report(aggregate)
    assert aggregate.matched_learner_count == measurement.matched_learner_count
    assert aggregate.mean_pre_score == measurement.mean_pre_score
    assert aggregate.mean_post_score == measurement.mean_post_score
    assert aggregate.mean_paired_delta == measurement.mean_paired_delta
    assert aggregate.median_paired_delta == measurement.median_paired_delta
    assert aggregate.improved_count == measurement.improved_count
    assert aggregate.unchanged_count == measurement.unchanged_count
    assert aggregate.declined_count == measurement.declined_count
    assert aggregate.missing_pre == aggregate.missing_post == 0
    assert aggregate.invalid_incomplete == 0
    assert aggregate.unsupported_verification == 0
    assert aggregate.indeterminate_verification == 0
    assert _PUBLIC_ID not in serialized
    assert "learner_id" not in serialized
    assert "student_id" not in serialized
    assert json.dumps(str(student.id)) not in serialized
    for question_id in all_question_ids | {
        row.transfer_question_id
        for row in db.scalars(select(TutorSession)).all()
        if row.transfer_question_id is not None
    }:
        assert json.dumps(question_id) not in serialized
    for skill_code, *_ in frozen_snapshot:
        assert json.dumps(skill_code) not in serialized
    for expected_answer in expected_answers:
        assert json.dumps(expected_answer) not in serialized

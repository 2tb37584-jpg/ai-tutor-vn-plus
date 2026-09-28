from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import tutor as tutor_api
from app.db.session import Base
from app.models import Student, TutorMessage, TutorSession, User
from app.models.entities import PilotEnrollment, PilotSkillAssignment
from app.schemas.tutor import (
    TutorReplyRequest,
    TutorState,
    TutorTurn,
)
from app.services import pilot_intervention


_RECEIVED_AT = datetime(2026, 5, 6, 7, 8, 9)
_SPECS = (
    ("arithmetic.signed_number_operations", "g8alg.signed-number-operations.001", "g8alg.signed-number-operations.002", "g8alg.signed-number-operations.003"),
    ("algebra.expression.distributive_property", "g8alg.distributive-property.001", "g8alg.distributive-property.002", "g8alg.distributive-property.003"),
    ("algebra.expression.combine_like_terms", "g8alg.combine-like-terms.001", "g8alg.combine-like-terms.002", "g8alg.combine-like-terms.003"),
    ("algebra.expression.simplify", "g8alg.expression-simplify.001", "g8alg.expression-simplify.002", "g8alg.expression-simplify.003"),
    ("algebra.identity.basic", "g8alg.identity-basic.001", "g8alg.identity-basic.002", "g8alg.identity-basic.003"),
    ("algebra.linear_equation", "g8alg.linear-equation.001", "g8alg.linear-equation.002", "g8alg.linear-equation.003"),
    ("algebra.equation.equivalent_transform", "g8alg.equivalent-transform.001", "g8alg.equivalent-transform.002", "g8alg.equivalent-transform.003"),
    ("algebra.factorization", "g8alg.factorization.001", "g8alg.factorization.002", "g8alg.factorization.003"),
    ("algebra.rational_expression.domain", "g8alg.rational-expression-domain.001", "g8alg.rational-expression-domain.002", "g8alg.rational-expression-domain.003"),
)


class FakeAI:
    def __init__(self, state: TutorState, *, likely_correct: bool = False) -> None:
        self.state = state
        self.likely_correct = likely_correct
        self.calls = 0

    def continue_turn(self, *_args, **_kwargs) -> TutorTurn:
        self.calls += 1
        return TutorTurn(
            message="Try the next small step.",
            state=self.state,
            likely_correct=self.likely_correct,
        )


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        owner = User(id=1, email="pilot-owner@example.com", password_hash="hash")
        student = Student(id=1, owner_id=owner.id, display_name="Synthetic learner", grade=8)
        session.add_all((owner, student))
        session.commit()
        yield session


def _setup_pilot(
    db: Session,
    *,
    session_index: int = 7,
    completed_prefix: int = 0,
    state: TutorState = TutorState.TRANSFER,
) -> tuple[User, PilotEnrollment, list[PilotSkillAssignment], TutorSession]:
    enrollment = PilotEnrollment(
        public_id=f"runtime-pilot-{id(db)}",
        student_id=1,
        phase="intervention",
    )
    db.add(enrollment)
    db.flush()
    assignments = [
        PilotSkillAssignment(
            pilot_enrollment_id=enrollment.id,
            skill_code=skill,
            pre_question_id=pre_id,
            learning_question_id=learning_id,
            post_question_id=post_id,
            pre_verification_status="correct" if index % 2 == 0 else "incorrect",
            pre_submitted_at=_RECEIVED_AT,
            learning_completed_at=_RECEIVED_AT if index < completed_prefix else None,
        )
        for index, (skill, pre_id, learning_id, post_id) in enumerate(_SPECS)
    ]
    db.add_all(assignments)
    db.flush()
    assigned = assignments[session_index]
    session = TutorSession(
        student_id=1,
        normalized_problem="original context must not authorize transfer",
        primary_skill=assigned.skill_code,
        current_state=state.value,
        internal_expected_answer="original answer must not authorize transfer",
        verification_family="numeric",
        authored_question_id=assigned.learning_question_id,
        transfer_question_id=(
            assigned.learning_question_id if state is TutorState.TRANSFER else None
        ),
        pilot_skill_assignment_id=assigned.id,
    )
    db.add(session)
    db.commit()
    user = db.get(User, 1)
    assert user is not None
    return user, enrollment, assignments, session


def _reply(
    db: Session,
    user: User,
    session: TutorSession,
    message: str = "(x+2)*(x+3)",
):
    return tutor_api.tutor_reply(
        TutorReplyRequest(session_id=session.id, student_message=message),
        user,
        db,
    )


def _silence_mastery(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tutor_api,
        "record_mastery_evidence",
        lambda *_args, **_kwargs: None,
    )


def test_pilot_context_validation_precedes_ai_and_message_side_effects(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, _, _, session = _setup_pilot(db)
    session.authored_question_id = "wrong.authored.question"
    ai = FakeAI(TutorState.TRANSFER)
    monkeypatch.setattr(tutor_api, "ai", ai)

    with pytest.raises(HTTPException) as error:
        _reply(db, user, session)

    assert error.value.status_code == 503
    assert error.value.detail == "Pilot learning is temporarily unavailable"
    assert ai.calls == 0
    assert db.scalars(select(TutorMessage)).all() == []


def test_unexpected_intervention_exception_propagates(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, _, _, session = _setup_pilot(db)
    monkeypatch.setattr(tutor_api, "ai", FakeAI(TutorState.COMPLETE))
    _silence_mastery(monkeypatch)
    monkeypatch.setattr(
        tutor_api,
        "complete_pilot_learning_assignment",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("unexpected")),
    )

    with pytest.raises(RuntimeError, match="unexpected"):
        _reply(db, user, session)


def test_entering_transfer_excludes_pre_post_and_keeps_learning_eligible(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, _, assignments, session = _setup_pilot(db, state=TutorState.VERIFY)
    monkeypatch.setattr(tutor_api, "_utcnow", lambda: _RECEIVED_AT)
    monkeypatch.setattr(tutor_api, "ai", FakeAI(TutorState.TRANSFER))
    _silence_mastery(monkeypatch)
    monkeypatch.setattr(
        tutor_api,
        "get_active_pilot_reserved_question_ids",
        lambda *_args, **_kwargs: pytest.fail("pilot provenance uses role-specific exclusions"),
    )

    response = _reply(db, user, session)

    assignment = assignments[7]
    assert response.tutor.state is TutorState.TRANSFER
    assert session.transfer_question_id == assignment.learning_question_id
    assert session.transfer_question_id not in {
        assignment.pre_question_id,
        assignment.post_question_id,
    }
    assert assignment.learning_question_id == "g8alg.factorization.002"
    assert assignment.pre_question_id == "g8alg.factorization.001"
    assert assignment.post_question_id == "g8alg.factorization.003"


def test_generic_transfer_entry_keeps_all_active_pilot_exclusions(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, _, _, session = _setup_pilot(db, state=TutorState.VERIFY)
    session.pilot_skill_assignment_id = None
    session.authored_question_id = None
    session.transfer_question_id = None
    session.normalized_problem = "5+0"
    session.internal_expected_answer = "5"
    session.verification_family = "numeric"
    frozen = ("frozen.pre", "frozen.learning", "frozen.post")
    received_exclusions: list[tuple[str, ...]] = []
    monkeypatch.setattr(tutor_api, "_utcnow", lambda: _RECEIVED_AT)
    monkeypatch.setattr(tutor_api, "ai", FakeAI(TutorState.TRANSFER))
    monkeypatch.setattr(
        tutor_api,
        "_reserved_question_ids_for_student_or_503",
        lambda *_args: frozen,
    )
    monkeypatch.setattr(
        tutor_api,
        "get_transfer_question_for_skill",
        lambda _skill, *, excluded_question_ids: received_exclusions.append(
            excluded_question_ids
        ) or None,
    )

    _reply(db, user, session, "5")

    assert received_exclusions == [frozen]


def test_non_pilot_active_enrollment_still_excludes_all_frozen_roles(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, _, _, session = _setup_pilot(db, state=TutorState.VERIFY)
    session.pilot_skill_assignment_id = None
    session.authored_question_id = None
    session.transfer_question_id = None
    session.normalized_problem = "x^2-9"
    session.internal_expected_answer = "x^2-9"
    session.verification_family = "expression_equivalence"
    frozen = (
        "g8alg.factorization.001",
        "g8alg.factorization.002",
        "g8alg.factorization.003",
    )
    monkeypatch.setattr(tutor_api, "_utcnow", lambda: _RECEIVED_AT)
    monkeypatch.setattr(tutor_api, "ai", FakeAI(TutorState.TRANSFER))
    monkeypatch.setattr(
        tutor_api,
        "_reserved_question_ids_for_student_or_503",
        lambda *_args: frozen,
    )
    _silence_mastery(monkeypatch)

    _reply(db, user, session, "(x-3)*(x+3)")

    assert session.transfer_question_id is None


@pytest.mark.parametrize(
    ("candidate", "likely_correct", "expected_state", "should_complete"),
    [
        ("not a factorization", True, TutorState.TRANSFER, False),
        ("(x+2)*(x+3)", False, TutorState.COMPLETE, True),
    ],
)
def test_deterministic_transfer_controls_state_and_pilot_completion(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    candidate: str,
    likely_correct: bool,
    expected_state: TutorState,
    should_complete: bool,
) -> None:
    user, _, assignments, session = _setup_pilot(db)
    monkeypatch.setattr(tutor_api, "_utcnow", lambda: _RECEIVED_AT)
    monkeypatch.setattr(tutor_api, "ai", FakeAI(TutorState.COMPLETE, likely_correct=likely_correct))
    _silence_mastery(monkeypatch)
    monkeypatch.setattr(
        tutor_api,
        "recommend_next_learning_question",
        lambda *_args, **_kwargs: pytest.fail("pilot progression bypasses generic recommender"),
    )

    response = _reply(db, user, session, candidate)

    assert response.tutor.state is expected_state
    assert session.current_state == expected_state.value
    assert assignments[7].learning_completed_at == (
        _RECEIVED_AT if should_complete else None
    )
    if should_complete:
        assert response.next_learning_action is not None
        assert response.next_learning_action.question_id == assignments[8].learning_question_id
    else:
        assert response.next_learning_action is None


def test_completion_timestamp_is_server_received_at_and_next_action_is_safe(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, _, assignments, session = _setup_pilot(db)
    monkeypatch.setattr(tutor_api, "_utcnow", lambda: _RECEIVED_AT)
    monkeypatch.setattr(tutor_api, "ai", FakeAI(TutorState.COMPLETE))
    _silence_mastery(monkeypatch)
    monkeypatch.setattr(
        tutor_api,
        "recommend_next_learning_question",
        lambda *_args, **_kwargs: pytest.fail("pilot progression must use persisted order"),
    )

    response = _reply(db, user, session)
    body = response.model_dump(mode="json")
    action = body["next_learning_action"]

    assert assignments[7].learning_completed_at == _RECEIVED_AT
    assert action["question_id"] == assignments[8].learning_question_id
    assert action["skill_code"] == assignments[8].skill_code
    assert set(action) == {"question_id", "skill_code", "problem_text", "difficulty"}
    for index, assignment in enumerate(assignments):
        assert assignment.pre_question_id not in str(action)
        assert assignment.post_question_id not in str(action)
        if index != 8:
            assert assignment.learning_question_id not in str(action)
    assert "expected_answer" not in str(action)
    assert "verification_reference" not in str(action)
    assert "verification_family" not in str(action)


def test_final_ninth_completion_moves_to_post_without_starting_assessment(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, enrollment, assignments, session = _setup_pilot(
        db,
        session_index=8,
        completed_prefix=8,
    )
    monkeypatch.setattr(tutor_api, "_utcnow", lambda: _RECEIVED_AT)
    monkeypatch.setattr(tutor_api, "ai", FakeAI(TutorState.COMPLETE))
    _silence_mastery(monkeypatch)
    monkeypatch.setattr(
        tutor_api,
        "recommend_next_learning_question",
        lambda *_args, **_kwargs: pytest.fail("pilot completion must not recommend"),
    )

    response = _reply(db, user, session, "x != -4")

    assert response.tutor.state is TutorState.COMPLETE
    assert enrollment.phase == "post"
    assert assignments[8].learning_completed_at == _RECEIVED_AT
    assert all(row.post_verification_status is None for row in assignments)
    assert all(row.post_submitted_at is None for row in assignments)
    assert response.next_learning_action is None
    assert db.query(TutorMessage).count() == 2
    assert db.query(PilotEnrollment).one().phase == "post"


def test_duplicate_session_completion_is_idempotent(db: Session, monkeypatch) -> None:
    user, _, assignments, first_session = _setup_pilot(db)
    monkeypatch.setattr(tutor_api, "_utcnow", lambda: _RECEIVED_AT)
    monkeypatch.setattr(tutor_api, "ai", FakeAI(TutorState.COMPLETE))
    _silence_mastery(monkeypatch)
    monkeypatch.setattr(
        tutor_api,
        "recommend_next_learning_question",
        lambda *_args, **_kwargs: pytest.fail("pilot duplicate completion must not recommend"),
    )
    _reply(db, user, first_session)
    first_completion = assignments[7].learning_completed_at

    duplicate = TutorSession(
        student_id=1,
        current_state=TutorState.TRANSFER.value,
        primary_skill=assignments[7].skill_code,
        authored_question_id=assignments[7].learning_question_id,
        transfer_question_id=assignments[7].learning_question_id,
        pilot_skill_assignment_id=assignments[7].id,
        internal_expected_answer="unused",
    )
    db.add(duplicate)
    db.commit()
    monkeypatch.setattr(tutor_api, "_utcnow", lambda: datetime(2026, 7, 8))

    response = _reply(db, user, duplicate)

    assert response.tutor.state is TutorState.COMPLETE
    assert assignments[7].learning_completed_at == first_completion
    assert assignments[8].learning_completed_at is None
    assert response.next_learning_action is not None
    assert response.next_learning_action.question_id == assignments[8].learning_question_id


def test_already_complete_followup_does_not_progress_or_recommend(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, _, assignments, session = _setup_pilot(db)
    first_time = datetime(2026, 1, 1)
    assignments[7].learning_completed_at = first_time
    session.current_state = TutorState.COMPLETE.value
    db.commit()
    monkeypatch.setattr(tutor_api, "ai", FakeAI(TutorState.COMPLETE))
    monkeypatch.setattr(
        tutor_api,
        "complete_pilot_learning_assignment",
        lambda *_args, **_kwargs: pytest.fail("already-complete session must not progress"),
    )
    monkeypatch.setattr(
        tutor_api,
        "recommend_next_learning_question",
        lambda *_args, **_kwargs: pytest.fail("already-complete session must not recommend"),
    )

    response = _reply(db, user, session)

    assert response.tutor.state is TutorState.COMPLETE
    assert response.next_learning_action is None
    assert assignments[7].learning_completed_at == first_time
    assert assignments[8].learning_completed_at is None


def test_progression_failure_rolls_back_pending_reply_and_completion(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, _, assignments, session = _setup_pilot(db)
    monkeypatch.setattr(tutor_api, "_utcnow", lambda: _RECEIVED_AT)
    monkeypatch.setattr(tutor_api, "ai", FakeAI(TutorState.COMPLETE))
    _silence_mastery(monkeypatch)
    monkeypatch.setattr(pilot_intervention, "get_question", lambda _question_id: None)

    with pytest.raises(HTTPException) as error:
        _reply(db, user, session)

    assert error.value.status_code == 503
    assert error.value.detail == "Pilot learning is temporarily unavailable"
    assert assignments[7].learning_completed_at is None
    db.expire_all()
    assert db.scalars(select(TutorMessage)).all() == []
    persisted = db.get(TutorSession, session.id)
    assert persisted is not None
    assert persisted.current_state == TutorState.TRANSFER.value


def test_non_pilot_transfer_completion_still_uses_generic_recommender(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, _, _, session = _setup_pilot(db)
    session.pilot_skill_assignment_id = None
    session.authored_question_id = "g8alg.factorization.001"
    session.transfer_question_id = "g8alg.factorization.001"
    session.normalized_problem = "x^2-9"
    session.internal_expected_answer = "(x-3)*(x+3)"
    session.verification_family = "factorization"
    recommendation = tutor_api.get_question("g8alg.linear-equation.001")
    assert recommendation is not None
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(tutor_api, "ai", FakeAI(TutorState.COMPLETE))
    _silence_mastery(monkeypatch)
    monkeypatch.setattr(tutor_api, "_reserved_question_ids_for_student_or_503", lambda *_args: ("frozen",))
    monkeypatch.setattr(
        tutor_api,
        "recommend_next_learning_question",
        lambda _db, **kwargs: calls.append(kwargs) or recommendation,
    )

    response = _reply(db, user, session, "(x-3)*(x+3)")

    assert response.tutor.state is TutorState.COMPLETE
    assert response.next_learning_action is not None
    assert response.next_learning_action.question_id == recommendation.id
    assert len(calls) == 1

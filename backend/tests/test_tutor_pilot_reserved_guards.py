from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api import tutor as tutor_api
from app.db.session import Base
from app.models import (
    Student,
    TutorMessage,
    TutorSession,
    User,
)
from app.models.entities import PilotEnrollment, PilotSkillAssignment
from app.schemas.tutor import (
    StartAuthoredTutorRequest,
    TutorReplyRequest,
    TutorState,
    TutorTurn,
)
from app.services.pilot_reserved_questions import PilotReservedQuestionStateError
from app.services.question_bank import get_question
from app.services.verifier import (
    NumericVerificationRequest,
    ProblemFamily,
    VerificationResult,
    VerificationStatus,
)


class FakeAI:
    def __init__(self, turn: TutorTurn) -> None:
        self.turn = turn
        self.calls = 0

    def first_turn(self, _analysis, _grade):
        self.calls += 1
        return self.turn

    def continue_turn(self, **_kwargs):
        self.calls += 1
        return self.turn


class FakeDatabase:
    def __init__(self, session: TutorSession, student: Student) -> None:
        self.session = session
        self.student = student
        self.messages: list[TutorMessage] = []
        self.commits = 0

    def get(self, model, record_id):
        if model is TutorSession:
            return self.session if record_id == self.session.id else None
        if model is Student:
            return self.student if record_id == self.student.id else None
        return None

    def scalars(self, _statement):
        return self.messages.copy()

    def add(self, item):
        if isinstance(item, TutorMessage):
            self.messages.append(item)

    def commit(self):
        self.commits += 1


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(email="owner@example.com", password_hash="hash")
        session.add(user)
        session.flush()
        session.add(Student(id=1, owner_id=user.id, display_name="Student", grade=8))
        session.commit()
        yield session


def add_active_assignments(db: Session) -> None:
    enrollment = PilotEnrollment(public_id="pilot-1", student_id=1, phase="pre")
    db.add(enrollment)
    db.flush()
    for index in range(9):
        if index == 0:
            pre_id, learning_id, post_id = (
                "g8alg.factorization.001",
                "g8alg.factorization.002",
                "g8alg.factorization.003",
            )
        else:
            pre_id, learning_id, post_id = (
                f"pre.{index}",
                f"learning.{index}",
                f"post.{index}",
            )
        db.add(
            PilotSkillAssignment(
                pilot_enrollment_id=enrollment.id,
                skill_code=f"skill.{index}",
                pre_question_id=pre_id,
                learning_question_id=learning_id,
                post_question_id=post_id,
            )
        )
    db.commit()


@pytest.mark.parametrize(
    "reserved_id",
    [
        "g8alg.factorization.001",
        "g8alg.factorization.002",
        "g8alg.factorization.003",
    ],
)
def test_authored_start_rejects_each_reserved_role(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    reserved_id: str,
) -> None:
    add_active_assignments(db)
    assert get_question(reserved_id) is not None
    ai = FakeAI(TutorTurn(message="first", state=TutorState.ASK_ATTEMPT))
    monkeypatch.setattr(tutor_api, "ai", ai)

    with pytest.raises(HTTPException) as error:
        tutor_api.start_authored_tutor(
            StartAuthoredTutorRequest(student_id=1, question_id=reserved_id),
            user=db.get(User, 1),
            db=db,
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Question not found"
    assert ai.calls == 0
    assert db.query(TutorSession).count() == 0
    assert db.query(TutorMessage).count() == 0


def test_completed_pilot_does_not_block_authored_start(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enrollment = PilotEnrollment(public_id="pilot-complete", student_id=1, phase="complete")
    db.add(enrollment)
    db.commit()
    ai = FakeAI(TutorTurn(message="first", state=TutorState.ASK_ATTEMPT))
    monkeypatch.setattr(tutor_api, "ai", ai)

    response = tutor_api.start_authored_tutor(
        StartAuthoredTutorRequest(
            student_id=1,
            question_id="g8alg.factorization.001",
        ),
        user=db.get(User, 1),
        db=db,
    )

    assert response.session_id is not None
    assert ai.calls == 1


def test_non_pilot_can_start_authored_item(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ai = FakeAI(TutorTurn(message="first", state=TutorState.ASK_ATTEMPT))
    monkeypatch.setattr(tutor_api, "ai", ai)

    response = tutor_api.start_authored_tutor(
        StartAuthoredTutorRequest(student_id=1, question_id="g8alg.factorization.001"),
        user=db.get(User, 1),
        db=db,
    )

    assert response.question.question_id == "g8alg.factorization.001"
    assert db.query(TutorSession).count() == 1
    assert db.query(TutorMessage).count() == 1


def test_active_pilot_allows_unreserved_authored_item(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_active_assignments(db)
    question_id = "g8alg.identity-basic.001"
    assert get_question(question_id) is not None
    ai = FakeAI(TutorTurn(message="first", state=TutorState.ASK_ATTEMPT))
    monkeypatch.setattr(tutor_api, "ai", ai)

    response = tutor_api.start_authored_tutor(
        StartAuthoredTutorRequest(student_id=1, question_id=question_id),
        user=db.get(User, 1),
        db=db,
    )

    assert response.question.question_id == question_id
    assert db.query(TutorSession).count() == 1
    assert db.query(TutorMessage).count() == 1
    assert ai.calls == 1


def test_malformed_active_state_maps_to_503_without_side_effects(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ai = FakeAI(TutorTurn(message="first", state=TutorState.ASK_ATTEMPT))
    monkeypatch.setattr(tutor_api, "ai", ai)
    monkeypatch.setattr(
        tutor_api,
        "get_active_pilot_reserved_question_ids",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PilotReservedQuestionStateError("malformed")
        ),
    )

    with pytest.raises(HTTPException) as error:
        tutor_api.start_authored_tutor(
            StartAuthoredTutorRequest(student_id=1, question_id="g8alg.factorization.001"),
            user=db.get(User, 1),
            db=db,
        )

    assert error.value.status_code == 503
    assert error.value.detail == "Tutor content is temporarily unavailable"
    assert db.query(TutorSession).count() == 0
    assert ai.calls == 0


def _fake_runtime_context(
    state: TutorState,
    *,
    transfer_question_id: str | None = None,
) -> tuple[FakeDatabase, TutorSession, FakeAI]:
    user = User(id=1, email="owner@example.com", password_hash="hash")
    student = Student(id=1, owner_id=1, display_name="Student", grade=8)
    session = TutorSession(
        id=1,
        student_id=1,
        current_state=state.value,
        normalized_problem="x + 1 = 2",
        primary_skill="algebra.factorization",
        internal_expected_answer="1",
        verification_family="numeric",
        transfer_question_id=transfer_question_id,
    )
    return FakeDatabase(session, student), session, FakeAI(
        TutorTurn(message="next", state=TutorState.COMPLETE)
    )


def test_transfer_and_recommendation_share_persisted_exclusions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, session, ai = _fake_runtime_context(
        TutorState.TRANSFER,
        transfer_question_id="g8alg.factorization.001",
    )
    reserved = ("pre.0", "learning.0", "post.0")
    monkeypatch.setattr(tutor_api, "ai", ai)
    monkeypatch.setattr(
        tutor_api,
        "get_active_pilot_reserved_question_ids",
        lambda *_args, **_kwargs: reserved,
    )
    monkeypatch.setattr(
        tutor_api,
        "_transfer_verification_request_for_session",
        lambda *_args: NumericVerificationRequest(
            family=ProblemFamily.NUMERIC,
            expected="1",
            candidate="1",
        ),
    )
    monkeypatch.setattr(
        tutor_api,
        "verify",
        lambda _request: VerificationResult(VerificationStatus.CORRECT),
    )
    monkeypatch.setattr(tutor_api, "record_mastery_evidence", lambda *_args: None)
    selected: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        tutor_api,
        "get_transfer_question_for_skill",
        lambda _skill, *, excluded_question_ids: (
            selected.append(excluded_question_ids) or None
        ),
    )
    recommendations: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        tutor_api,
        "recommend_next_learning_question",
        lambda _db, **kwargs: recommendations.append(kwargs["excluded_question_ids"]) or None,
    )

    response = tutor_api.tutor_reply(
        TutorReplyRequest(session_id=1, student_message="answer"),
        user=User(id=1, email="owner@example.com", password_hash="hash"),
        db=db,
    )

    assert selected == []
    assert recommendations == [reserved]
    assert response.next_learning_action is None
    assert session.current_state == TutorState.COMPLETE.value


def test_transfer_selection_receives_exclusions_and_preserves_none_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, session, ai = _fake_runtime_context(TutorState.VERIFY)
    ai.turn = TutorTurn(message="transfer", state=TutorState.TRANSFER)
    reserved = ("pre.0", "learning.0", "post.0")
    received: list[tuple[str, ...]] = []
    monkeypatch.setattr(tutor_api, "ai", ai)
    monkeypatch.setattr(
        tutor_api,
        "get_active_pilot_reserved_question_ids",
        lambda *_args, **_kwargs: reserved,
    )
    monkeypatch.setattr(tutor_api, "_verification_request_for_session", lambda *_args: None)
    monkeypatch.setattr(
        tutor_api,
        "get_transfer_question_for_skill",
        lambda _skill, *, excluded_question_ids: received.append(excluded_question_ids) or None,
    )

    tutor_api.tutor_reply(
        TutorReplyRequest(session_id=1, student_message="answer"),
        user=User(id=1, email="owner@example.com", password_hash="hash"),
        db=db,
    )

    assert received == [reserved]
    assert session.transfer_question_id is None
    assert session.current_state == TutorState.TRANSFER.value


def test_transfer_selection_uses_real_selector_to_skip_reserved_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, session, ai = _fake_runtime_context(TutorState.VERIFY)
    ai.turn = TutorTurn(message="transfer", state=TutorState.TRANSFER)
    monkeypatch.setattr(tutor_api, "ai", ai)
    monkeypatch.setattr(
        tutor_api,
        "get_active_pilot_reserved_question_ids",
        lambda *_args, **_kwargs: ("g8alg.factorization.001",),
    )
    monkeypatch.setattr(tutor_api, "_verification_request_for_session", lambda *_args: None)

    tutor_api.tutor_reply(
        TutorReplyRequest(session_id=1, student_message="answer"),
        user=User(id=1, email="owner@example.com", password_hash="hash"),
        db=db,
    )

    assert session.transfer_question_id == "g8alg.factorization.002"


def test_non_pilot_transfer_receives_empty_exclusions_and_keeps_existing_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, session, ai = _fake_runtime_context(TutorState.VERIFY)
    ai.turn = TutorTurn(message="transfer", state=TutorState.TRANSFER)
    received: list[tuple[str, ...]] = []
    monkeypatch.setattr(tutor_api, "ai", ai)
    monkeypatch.setattr(
        tutor_api,
        "get_active_pilot_reserved_question_ids",
        lambda *_args, **_kwargs: (),
    )
    monkeypatch.setattr(tutor_api, "_verification_request_for_session", lambda *_args: None)
    monkeypatch.setattr(
        tutor_api,
        "get_transfer_question_for_skill",
        lambda _skill, *, excluded_question_ids: (
            received.append(excluded_question_ids)
            or SimpleNamespace(id="unreserved.transfer")
        ),
    )

    tutor_api.tutor_reply(
        TutorReplyRequest(session_id=1, student_message="answer"),
        user=User(id=1, email="owner@example.com", password_hash="hash"),
        db=db,
    )

    assert received == [()]
    assert session.transfer_question_id == "unreserved.transfer"


def test_recommendation_for_non_pilot_receives_empty_exclusions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, session, ai = _fake_runtime_context(
        TutorState.TRANSFER,
        transfer_question_id="g8alg.factorization.001",
    )
    received: list[tuple[str, ...]] = []
    monkeypatch.setattr(tutor_api, "ai", ai)
    monkeypatch.setattr(
        tutor_api,
        "get_active_pilot_reserved_question_ids",
        lambda *_args, **_kwargs: (),
    )
    monkeypatch.setattr(
        tutor_api,
        "_transfer_verification_request_for_session",
        lambda *_args: NumericVerificationRequest(
            family=ProblemFamily.NUMERIC,
            expected="1",
            candidate="1",
        ),
    )
    monkeypatch.setattr(
        tutor_api,
        "verify",
        lambda _request: VerificationResult(VerificationStatus.CORRECT),
    )
    monkeypatch.setattr(tutor_api, "record_mastery_evidence", lambda *_args: None)
    monkeypatch.setattr(
        tutor_api,
        "recommend_next_learning_question",
        lambda _db, **kwargs: received.append(kwargs["excluded_question_ids"]) or None,
    )

    tutor_api.tutor_reply(
        TutorReplyRequest(session_id=1, student_message="answer"),
        user=User(id=1, email="owner@example.com", password_hash="hash"),
        db=db,
    )

    assert received == [()]


def test_existing_transfer_id_is_not_reselected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, session, ai = _fake_runtime_context(
        TutorState.VERIFY,
        transfer_question_id="persisted.transfer",
    )
    ai.turn = TutorTurn(message="transfer", state=TutorState.TRANSFER)
    monkeypatch.setattr(tutor_api, "ai", ai)
    monkeypatch.setattr(tutor_api, "get_active_pilot_reserved_question_ids", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(tutor_api, "_verification_request_for_session", lambda *_args: None)
    monkeypatch.setattr(
        tutor_api,
        "get_transfer_question_for_skill",
        lambda *_args, **_kwargs: pytest.fail("persisted transfer ID was reselected"),
    )

    tutor_api.tutor_reply(
        TutorReplyRequest(session_id=1, student_message="answer"),
        user=User(id=1, email="owner@example.com", password_hash="hash"),
        db=db,
    )

    assert session.transfer_question_id == "persisted.transfer"


def test_corrupt_reservation_state_fails_closed_for_tutor_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, _session, ai = _fake_runtime_context(TutorState.TRANSFER)
    monkeypatch.setattr(tutor_api, "ai", ai)
    monkeypatch.setattr(
        tutor_api,
        "get_active_pilot_reserved_question_ids",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PilotReservedQuestionStateError("reserved ids unavailable")
        ),
    )

    with pytest.raises(HTTPException) as error:
        tutor_api.tutor_reply(
            TutorReplyRequest(session_id=1, student_message="answer"),
            user=User(id=1, email="owner@example.com", password_hash="hash"),
            db=db,
        )

    assert error.value.status_code == 503
    assert error.value.detail == "Tutor content is temporarily unavailable"
    assert "reserved" not in error.value.detail
    assert db.messages == []
    assert ai.calls == 0


def test_unexpected_resolver_error_propagates_before_tutor_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, _session, ai = _fake_runtime_context(TutorState.TRANSFER)
    monkeypatch.setattr(tutor_api, "ai", ai)
    monkeypatch.setattr(
        tutor_api,
        "get_active_pilot_reserved_question_ids",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        tutor_api.tutor_reply(
            TutorReplyRequest(session_id=1, student_message="answer"),
            user=User(id=1, email="owner@example.com", password_hash="hash"),
            db=db,
        )

    assert db.messages == []
    assert db.commits == 0
    assert ai.calls == 0

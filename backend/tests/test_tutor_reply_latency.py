from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.api import tutor as tutor_api
from app.models import Student, TutorMessage, TutorSession, User
from app.schemas.tutor import TutorReplyIntent, TutorReplyRequest, TutorState, TutorTurn


class FakeDatabase:
    def __init__(
        self,
        student: Student,
        session: TutorSession,
        messages: list[TutorMessage] | None = None,
    ) -> None:
        self.student = student
        self.session = session
        self.messages = list(messages or [])
        self.commits = 0

    def get(self, model: type[object], record_id: int) -> object | None:
        if model is Student and record_id == self.student.id:
            return self.student
        if model is TutorSession and record_id == self.session.id:
            return self.session
        return None

    def scalars(self, _statement: object) -> list[TutorMessage]:
        return self.messages.copy()

    def add(self, record: object) -> None:
        if isinstance(record, TutorMessage):
            self.messages.append(record)

    def commit(self) -> None:
        self.commits += 1


class FakeTutorAI:
    def __init__(self) -> None:
        self.calls = 0

    def continue_turn(
        self,
        problem: str,
        skill: str,
        history: list[tuple[str, str]],
        student_message: str,
        *,
        current_state: TutorState,
        intent: TutorReplyIntent = TutorReplyIntent.ATTEMPT,
    ) -> TutorTurn:
        self.calls += 1
        state = TutorState.HINT_1 if intent is TutorReplyIntent.HINT_REQUEST else current_state
        return TutorTurn(message="Next question", state=state)


def _context(
    current_state: TutorState = TutorState.ASK_ATTEMPT,
    messages: list[TutorMessage] | None = None,
) -> tuple[User, FakeDatabase]:
    user = User(id=1, email="parent@example.com", password_hash="hash")
    student = Student(id=2, owner_id=user.id, display_name="Student", grade=8)
    session = TutorSession(
        id=3,
        student_id=student.id,
        normalized_problem="Solve x + 1 = 2",
        primary_skill="algebra.linear_equation",
        current_state=current_state.value,
        internal_expected_answer="1",
    )
    return user, FakeDatabase(student, session, messages)


def _assistant_message(created_at: datetime) -> TutorMessage:
    return TutorMessage(
        id=1,
        session_id=3,
        role="assistant",
        content="First question",
        created_at=created_at,
    )


def _student_messages(db: FakeDatabase) -> list[TutorMessage]:
    return [message for message in db.messages if message.role == "user"]


def _new_assistant_message(db: FakeDatabase) -> TutorMessage:
    return [message for message in db.messages if message.role == "assistant"][-1]


def test_attempt_persists_intent_and_reply_latency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous_at = datetime(2026, 1, 1, 12, 0, 0)
    received_at = previous_at + timedelta(milliseconds=2500)
    user, db = _context(messages=[_assistant_message(previous_at)])
    monkeypatch.setattr(tutor_api, "ai", FakeTutorAI())
    monkeypatch.setattr(tutor_api, "_utcnow", lambda: received_at)

    tutor_api.tutor_reply(
        TutorReplyRequest(session_id=3, student_message="x = 1"),
        user,
        db,
    )

    student_message = _student_messages(db)[0]
    assert student_message.reply_intent == "attempt"
    assert student_message.response_latency_ms == 2500
    assistant_message = _new_assistant_message(db)
    assert assistant_message.reply_intent is None
    assert assistant_message.response_latency_ms is None


def test_hint_request_persists_intent_and_reply_latency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous_at = datetime(2026, 1, 1, 12, 0, 0)
    received_at = previous_at + timedelta(milliseconds=1750)
    user, db = _context(messages=[_assistant_message(previous_at)])
    fake_ai = FakeTutorAI()
    monkeypatch.setattr(tutor_api, "ai", fake_ai)
    monkeypatch.setattr(tutor_api, "_utcnow", lambda: received_at)

    tutor_api.tutor_reply(
        TutorReplyRequest(
            session_id=3,
            student_message="Cho em gợi ý",
            intent=TutorReplyIntent.HINT_REQUEST,
        ),
        user,
        db,
    )

    student_message = _student_messages(db)[0]
    assert student_message.reply_intent == "hint_request"
    assert student_message.response_latency_ms == 1750
    assert fake_ai.calls == 1


def test_rejected_hint_request_persists_no_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = _assistant_message(datetime(2026, 1, 1, 12, 0, 0))
    user, db = _context(TutorState.VERIFY, [prior])
    fake_ai = FakeTutorAI()
    monkeypatch.setattr(tutor_api, "ai", fake_ai)

    with pytest.raises(HTTPException) as error:
        tutor_api.tutor_reply(
            TutorReplyRequest(
                session_id=3,
                student_message="Cho em gợi ý",
                intent=TutorReplyIntent.HINT_REQUEST,
            ),
            user,
            db,
        )

    assert error.value.status_code == 409
    assert db.messages == [prior]
    assert fake_ai.calls == 0
    assert db.commits == 0


def test_no_prior_assistant_persists_null_latency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, db = _context()
    monkeypatch.setattr(tutor_api, "ai", FakeTutorAI())
    monkeypatch.setattr(tutor_api, "_utcnow", lambda: datetime(2026, 1, 1, 12, 0, 0))

    tutor_api.tutor_reply(
        TutorReplyRequest(session_id=3, student_message="My attempt"),
        user,
        db,
    )

    student_message = _student_messages(db)[0]
    assert student_message.reply_intent == "attempt"
    assert student_message.response_latency_ms is None


def test_prior_assistant_without_timestamp_persists_null_latency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous_assistant = TutorMessage(
        id=1,
        session_id=3,
        role="assistant",
        content="First question",
        created_at=None,
    )
    user, db = _context(messages=[previous_assistant])
    monkeypatch.setattr(tutor_api, "ai", FakeTutorAI())
    monkeypatch.setattr(tutor_api, "_utcnow", lambda: datetime(2026, 1, 1, 12, 0, 0))

    tutor_api.tutor_reply(
        TutorReplyRequest(session_id=3, student_message="My attempt"),
        user,
        db,
    )

    student_message = _student_messages(db)[0]
    assert student_message.reply_intent == "attempt"
    assert student_message.response_latency_ms is None


def test_negative_reply_latency_is_clamped_to_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received_at = datetime(2026, 1, 1, 12, 0, 0)
    future_assistant = _assistant_message(received_at + timedelta(seconds=1))
    user, db = _context(messages=[future_assistant])
    monkeypatch.setattr(tutor_api, "ai", FakeTutorAI())
    monkeypatch.setattr(tutor_api, "_utcnow", lambda: received_at)

    tutor_api.tutor_reply(
        TutorReplyRequest(session_id=3, student_message="My attempt"),
        user,
        db,
    )

    assert _student_messages(db)[0].response_latency_ms == 0

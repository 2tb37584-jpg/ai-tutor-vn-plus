import pytest
from fastapi import HTTPException

from app.api import tutor as tutor_api
from app.models import Student, TutorMessage, TutorSession, User
from app.schemas.tutor import TutorState
from app.services.session_summary import summarize_tutor_session


def _session(current_state: str = "hint_2") -> TutorSession:
    return TutorSession(
        id=3,
        student_id=2,
        normalized_problem="Solve x + 1 = 2",
        primary_skill="algebra.linear_equation",
        current_state=current_state,
        internal_expected_answer="1",
    )


def _message(
    role: str,
    *,
    intent: str | None = None,
    latency: int | None = None,
) -> TutorMessage:
    return TutorMessage(
        session_id=3,
        role=role,
        content="not exposed",
        reply_intent=intent,
        response_latency_ms=latency,
    )


def test_mixed_attempt_and_hint_summary() -> None:
    session = _session()
    messages = [
        _message("user", intent="attempt", latency=1000),
        _message("user", intent="attempt", latency=2000),
        _message("user", intent="hint_request", latency=3000),
    ]

    summary = summarize_tutor_session(session, messages)

    assert summary.session_id == 3
    assert summary.primary_skill == "algebra.linear_equation"
    assert summary.current_state is TutorState.HINT_2
    assert summary.student_reply_count == 3
    assert summary.attempt_reply_count == 2
    assert summary.hint_request_count == 1
    assert summary.unclassified_reply_count == 0
    assert summary.timed_reply_count == 3
    assert summary.average_response_latency_ms == 2000.0


def test_legacy_unknown_and_missing_latency_are_summarized() -> None:
    messages = [
        _message("user", intent=None, latency=None),
        _message("user", intent="legacy_other", latency=4000),
        _message("user", intent="attempt", latency=None),
    ]

    summary = summarize_tutor_session(_session(), messages)

    assert summary.student_reply_count == 3
    assert summary.attempt_reply_count == 1
    assert summary.hint_request_count == 0
    assert summary.unclassified_reply_count == 2
    assert summary.student_reply_count == (
        summary.attempt_reply_count
        + summary.hint_request_count
        + summary.unclassified_reply_count
    )
    assert summary.timed_reply_count == 1
    assert summary.average_response_latency_ms == 4000.0


def test_no_timed_replies_and_assistant_telemetry_are_ignored() -> None:
    messages = [
        _message("user", intent="attempt", latency=None),
        _message("user", intent="hint_request", latency=None),
        _message("assistant", intent="attempt", latency=9999),
    ]

    summary = summarize_tutor_session(_session(), messages)

    assert summary.student_reply_count == 2
    assert summary.attempt_reply_count == 1
    assert summary.hint_request_count == 1
    assert summary.unclassified_reply_count == 0
    assert summary.timed_reply_count == 0
    assert summary.average_response_latency_ms is None


class FakeDatabase:
    def __init__(
        self,
        student: Student,
        session: TutorSession | None,
        messages: list[TutorMessage] | None = None,
    ) -> None:
        self.student = student
        self.session = session
        self.messages = list(messages or [])
        self.commits = 0
        self.adds = 0

    def get(self, model: type[object], record_id: int) -> object | None:
        if model is Student and record_id == self.student.id:
            return self.student
        if model is TutorSession and self.session is not None and record_id == self.session.id:
            return self.session
        return None

    def scalars(self, _statement: object) -> list[TutorMessage]:
        return self.messages.copy()

    def add(self, _record: object) -> None:
        self.adds += 1

    def commit(self) -> None:
        self.commits += 1


class FailingAI:
    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"Summary endpoint must not access AI attribute {name}")


def _endpoint_context(
    session: TutorSession | None = None,
    messages: list[TutorMessage] | None = None,
    *,
    owner_id: int = 1,
) -> tuple[User, FakeDatabase]:
    user = User(id=1, email="parent@example.com", password_hash="hash")
    student = Student(id=2, owner_id=owner_id, display_name="Student", grade=8)
    return user, FakeDatabase(student, session, messages)


def test_owned_summary_endpoint_is_read_only_and_does_not_call_ai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages = [
        _message("assistant", intent="attempt", latency=9999),
        _message("user", intent="attempt", latency=1000),
        _message("user", intent="hint_request", latency=3000),
    ]
    user, db = _endpoint_context(_session(), messages)
    monkeypatch.setattr(tutor_api, "ai", FailingAI())

    response = tutor_api.tutor_session_summary(3, user, db)

    assert response.student_reply_count == 2
    assert response.average_response_latency_ms == 2000.0
    assert db.adds == 0
    assert db.commits == 0


def test_missing_session_preserves_owned_session_404() -> None:
    user, db = _endpoint_context(None)

    with pytest.raises(HTTPException) as error:
        tutor_api.tutor_session_summary(3, user, db)

    assert error.value.status_code == 404
    assert error.value.detail == "Session not found"


def test_not_owned_session_preserves_owned_session_404() -> None:
    user, db = _endpoint_context(_session(), owner_id=99)

    with pytest.raises(HTTPException) as error:
        tutor_api.tutor_session_summary(3, user, db)

    assert error.value.status_code == 404
    assert error.value.detail == "Student not found"


def test_invalid_persisted_state_returns_existing_500() -> None:
    user, db = _endpoint_context(_session("invalid_state"))

    with pytest.raises(HTTPException) as error:
        tutor_api.tutor_session_summary(3, user, db)

    assert error.value.status_code == 500
    assert error.value.detail == "Tutor session is unavailable"
    assert db.adds == 0
    assert db.commits == 0

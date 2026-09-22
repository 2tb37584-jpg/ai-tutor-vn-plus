import logging

import pytest

from app.api import tutor as tutor_api
from app.models import Student, TutorMessage, TutorSession, User
from app.schemas.tutor import TutorReplyIntent, TutorReplyRequest, TutorState, TutorTurn
from app.services.verifier import VerificationResult, VerificationStatus


class FakeDatabase:
    def __init__(self, session: TutorSession) -> None:
        self.student = Student(id=session.student_id, owner_id=1, display_name="Student", grade=8)
        self.session = session
        self.messages = [TutorMessage(session_id=session.id, role="assistant", content="Start")]

    def get(self, model: type[object], record_id: int) -> object | None:
        if model is Student and record_id == self.student.id:
            return self.student
        if model is TutorSession and record_id == self.session.id:
            return self.session
        return None

    def add(self, record: object) -> None:
        if isinstance(record, TutorMessage):
            self.messages.append(record)

    def commit(self) -> None:
        pass

    def scalars(self, _statement: object) -> list[TutorMessage]:
        return self.messages.copy()


class FakeTutorAI:
    def __init__(self, turn: TutorTurn) -> None:
        self.turn = turn

    def continue_turn(
        self,
        problem: str,
        skill: str,
        history: list[tuple[str, str]],
        student_message: str,
        *,
        current_state: TutorState,
        intent: TutorReplyIntent | None = None,
    ) -> TutorTurn:
        return self.turn


def reply_context(
    *,
    current_state: TutorState = TutorState.ASK_ATTEMPT,
    verification_family: str | None = "numeric",
) -> tuple[User, TutorSession, FakeDatabase]:
    user = User(id=1, email="parent@example.com", password_hash="hash")
    session = TutorSession(
        id=2,
        student_id=1,
        normalized_problem="2 + 2",
        primary_skill="algebra.linear_equation",
        current_state=current_state.value,
        internal_expected_answer="4",
        verification_family=verification_family,
    )
    return user, session, FakeDatabase(session)


def reply(
    user: User,
    session: TutorSession,
    db: FakeDatabase,
    *,
    intent: TutorReplyIntent = TutorReplyIntent.ATTEMPT,
    message: str = "4",
):
    return tutor_api.tutor_reply(
        TutorReplyRequest(session_id=session.id, student_message=message, intent=intent),
        user,
        db,
    )


def telemetry_messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("event=tutor_verification_decision")
    ]


def configure_deterministic_reply(
    monkeypatch: pytest.MonkeyPatch,
    statuses: list[VerificationStatus],
    turn: TutorTurn,
) -> None:
    pending_statuses = iter(statuses)
    monkeypatch.setattr(tutor_api, "ai", FakeTutorAI(turn))
    monkeypatch.setattr(
        tutor_api,
        "verify",
        lambda _request: VerificationResult(next(pending_statuses)),
    )
    monkeypatch.setattr(tutor_api, "record_mastery_evidence", lambda _db, _event: None)


@pytest.mark.parametrize(
    ("status", "model_likely_correct", "expected_disagreement"),
    [
        (VerificationStatus.CORRECT, False, True),
        (VerificationStatus.INCORRECT, True, True),
    ],
)
def test_final_deterministic_verdict_logs_one_safe_event(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    status: VerificationStatus,
    model_likely_correct: bool,
    expected_disagreement: bool,
) -> None:
    user, session, db = reply_context()
    configure_deterministic_reply(
        monkeypatch,
        [status],
        TutorTurn(
            message="Tutor response",
            state=TutorState.HINT_1,
            likely_correct=model_likely_correct,
        ),
    )
    caplog.set_level(logging.INFO, logger=tutor_api.logger.name)

    reply(user, session, db)

    assert telemetry_messages(caplog) == [
        "event=tutor_verification_decision "
        "session_id=2 skill_code=algebra.linear_equation problem_family=numeric "
        f"verifier_status={status.value} model_likely_correct={str(model_likely_correct).lower()} "
        f"disagreement={str(expected_disagreement).lower()} retry_count=0 "
        "escalation_outcome=accept_deterministic mastery_eligible=true "
        "verification_method=numeric"
    ]


@pytest.mark.parametrize(
    ("statuses", "final_status", "escalation_outcome"),
    [
        (
            [VerificationStatus.INDETERMINATE, VerificationStatus.CORRECT],
            VerificationStatus.CORRECT,
            "accept_deterministic",
        ),
        (
            [VerificationStatus.INDETERMINATE, VerificationStatus.INDETERMINATE],
            VerificationStatus.INDETERMINATE,
            "model_assisted_only",
        ),
    ],
)
def test_retry_logs_only_the_final_deterministic_verdict(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    statuses: list[VerificationStatus],
    final_status: VerificationStatus,
    escalation_outcome: str,
) -> None:
    user, session, db = reply_context()
    configure_deterministic_reply(
        monkeypatch,
        statuses,
        TutorTurn(message="Tutor response", state=TutorState.HINT_1),
    )
    caplog.set_level(logging.INFO, logger=tutor_api.logger.name)

    reply(user, session, db)

    messages = telemetry_messages(caplog)
    assert len(messages) == 1
    assert f"verifier_status={final_status.value}" in messages[0]
    assert "retry_count=1" in messages[0]
    assert f"escalation_outcome={escalation_outcome}" in messages[0]


def test_verify_state_logs_but_is_not_mastery_eligible(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    user, session, db = reply_context(current_state=TutorState.VERIFY)
    configure_deterministic_reply(
        monkeypatch,
        [VerificationStatus.CORRECT],
        TutorTurn(message="Tutor response", state=TutorState.COMPLETE),
    )
    caplog.set_level(logging.INFO, logger=tutor_api.logger.name)

    reply(user, session, db)

    assert len(telemetry_messages(caplog)) == 1
    assert "mastery_eligible=false" in telemetry_messages(caplog)[0]


def test_supported_verifier_unsupported_result_is_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    user, session, db = reply_context()
    configure_deterministic_reply(
        monkeypatch,
        [VerificationStatus.UNSUPPORTED],
        TutorTurn(message="Tutor response", state=TutorState.HINT_1),
    )
    caplog.set_level(logging.INFO, logger=tutor_api.logger.name)

    reply(user, session, db)

    messages = telemetry_messages(caplog)
    assert len(messages) == 1
    assert "verifier_status=unsupported" in messages[0]
    assert "retry_count=0" in messages[0]
    assert "escalation_outcome=model_assisted_only" in messages[0]
    assert "mastery_eligible=false" in messages[0]


@pytest.mark.parametrize(
    ("verification_family", "intent"),
    [
        ("numeric", TutorReplyIntent.HINT_REQUEST),
        (None, TutorReplyIntent.ATTEMPT),
        ("unsupported_family", TutorReplyIntent.ATTEMPT),
    ],
)
def test_paths_without_deterministic_verification_emit_no_telemetry(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    verification_family: str | None,
    intent: TutorReplyIntent,
) -> None:
    user, session, db = reply_context(verification_family=verification_family)
    monkeypatch.setattr(
        tutor_api,
        "ai",
        FakeTutorAI(TutorTurn(message="Tutor response", state=TutorState.HINT_1)),
    )
    monkeypatch.setattr(tutor_api, "record_mastery_evidence", lambda _db, _event: None)
    caplog.set_level(logging.INFO, logger=tutor_api.logger.name)

    reply(user, session, db, intent=intent)

    assert telemetry_messages(caplog) == []


def test_telemetry_excludes_student_and_tutor_content(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    user, session, db = reply_context()
    session.normalized_problem = "SENTINEL_NORMALIZED_PROBLEM"
    session.internal_expected_answer = "SENTINEL_EXPECTED_ANSWER"
    configure_deterministic_reply(
        monkeypatch,
        [VerificationStatus.CORRECT],
        TutorTurn(
            message="SENTINEL_TUTOR_MESSAGE",
            state=TutorState.HINT_1,
            likely_correct=True,
        ),
    )
    caplog.set_level(logging.INFO, logger=tutor_api.logger.name)

    reply(user, session, db, message="SENTINEL_STUDENT_MESSAGE")

    output = "\n".join(telemetry_messages(caplog))
    assert "SENTINEL_STUDENT_MESSAGE" not in output
    assert "SENTINEL_NORMALIZED_PROBLEM" not in output
    assert "SENTINEL_EXPECTED_ANSWER" not in output
    assert "SENTINEL_TUTOR_MESSAGE" not in output

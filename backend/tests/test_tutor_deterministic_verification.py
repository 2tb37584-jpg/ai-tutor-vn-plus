import pytest

from app.api import tutor as tutor_api
from app.models import Student, TutorMessage, TutorSession, User
from app.schemas.tutor import TutorReplyIntent, TutorReplyRequest, TutorState, TutorTurn
from app.services.verifier import (
    ExpressionEquivalenceRequest,
    LinearEquationRequest,
    NumericVerificationRequest,
    VerificationResult,
    VerificationStatus,
)


class FakeDatabase:
    def __init__(self, student: Student, session: TutorSession) -> None:
        self.student = student
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
        self.intents: list[TutorReplyIntent | None] = []

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
        self.intents.append(intent)
        return self.turn


def reply_context(
    verification_family: str | None,
    current_state: TutorState = TutorState.ASK_ATTEMPT,
) -> tuple[User, TutorSession, FakeDatabase]:
    user = User(id=1, email="parent@example.com", password_hash="hash")
    student = Student(id=1, owner_id=1, display_name="Student", grade=8)
    session = TutorSession(
        id=1,
        student_id=1,
        normalized_problem="2*x+3=7",
        primary_skill="skill.test",
        current_state=current_state.value,
        internal_expected_answer="1/2",
        verification_family=verification_family,
    )
    return user, session, FakeDatabase(student, session)


def reply(
    user: User,
    session: TutorSession,
    db: FakeDatabase,
    message: str = "0.5",
    intent: TutorReplyIntent = TutorReplyIntent.ATTEMPT,
):
    return tutor_api.tutor_reply(
        TutorReplyRequest(session_id=session.id, student_message=message, intent=intent),
        user,
        db,
    )


def test_numeric_correct_overrides_model_and_persists_verify_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, session, db = reply_context("numeric")
    monkeypatch.setattr(
        tutor_api,
        "ai",
        FakeTutorAI(TutorTurn(message="Try again", state=TutorState.HINT_1, likely_correct=False)),
    )
    requests: list[object] = []

    def fake_verify(request: object) -> VerificationResult:
        requests.append(request)
        return VerificationResult(VerificationStatus.CORRECT)

    monkeypatch.setattr(tutor_api, "verify", fake_verify)

    response = reply(user, session, db)

    assert isinstance(requests[0], NumericVerificationRequest)
    assert requests[0].expected == "1/2"
    assert requests[0].candidate == "0.5"
    assert response.tutor.state is TutorState.VERIFY
    assert response.tutor.hint_level == 0
    assert session.current_state == response.tutor.state.value


def test_numeric_incorrect_overrides_model_and_escalates_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, session, db = reply_context("numeric")
    monkeypatch.setattr(
        tutor_api,
        "ai",
        FakeTutorAI(TutorTurn(message="Looks right", state=TutorState.VERIFY, likely_correct=True)),
    )
    monkeypatch.setattr(
        tutor_api,
        "verify",
        lambda _request: VerificationResult(VerificationStatus.INCORRECT),
    )

    response = reply(user, session, db)

    assert response.tutor.state is TutorState.HINT_1
    assert response.tutor.hint_level == 1
    assert session.current_state == response.tutor.state.value


@pytest.mark.parametrize(
    ("family", "request_type"),
    [
        ("expression_equivalence", ExpressionEquivalenceRequest),
        ("linear_equation", LinearEquationRequest),
    ],
)
def test_reply_builds_persisted_family_request(
    monkeypatch: pytest.MonkeyPatch,
    family: str,
    request_type: type[object],
) -> None:
    user, session, db = reply_context(family)
    monkeypatch.setattr(
        tutor_api,
        "ai",
        FakeTutorAI(TutorTurn(message="Message", state=TutorState.ASK_ATTEMPT)),
    )
    requests: list[object] = []
    monkeypatch.setattr(
        tutor_api,
        "verify",
        lambda request: requests.append(request) or VerificationResult(VerificationStatus.UNSUPPORTED),
    )

    reply(user, session, db, message="student candidate")

    assert isinstance(requests[0], request_type)
    if isinstance(requests[0], ExpressionEquivalenceRequest):
        assert requests[0].left == session.internal_expected_answer
        assert requests[0].right == "student candidate"
    else:
        assert isinstance(requests[0], LinearEquationRequest)
        assert requests[0].equation == session.normalized_problem
        assert requests[0].candidate == "student candidate"


@pytest.mark.parametrize(
    ("status", "expected_state"),
    [
        (VerificationStatus.CORRECT, TutorState.TRANSFER),
        (VerificationStatus.INCORRECT, TutorState.EXPLAIN_STEP),
    ],
)
def test_verify_state_uses_deterministic_verification_event(
    monkeypatch: pytest.MonkeyPatch,
    status: VerificationStatus,
    expected_state: TutorState,
) -> None:
    user, session, db = reply_context("numeric", TutorState.VERIFY)
    monkeypatch.setattr(
        tutor_api,
        "ai",
        FakeTutorAI(TutorTurn(message="Model response", state=TutorState.VERIFY)),
    )
    monkeypatch.setattr(
        tutor_api,
        "verify",
        lambda _request: VerificationResult(status),
    )

    response = reply(user, session, db)

    assert response.tutor.state is expected_state
    assert response.tutor.hint_level == 0
    assert session.current_state == response.tutor.state.value


@pytest.mark.parametrize(
    ("statuses", "expected_calls", "expected_state"),
    [
        ([VerificationStatus.UNSUPPORTED], 1, TutorState.ASK_ATTEMPT),
        ([VerificationStatus.INDETERMINATE, VerificationStatus.CORRECT], 2, TutorState.VERIFY),
        ([VerificationStatus.INDETERMINATE, VerificationStatus.INDETERMINATE], 2, TutorState.ASK_ATTEMPT),
    ],
)
def test_unknown_or_retried_deterministic_results_control_authoritative_state(
    monkeypatch: pytest.MonkeyPatch,
    statuses: list[VerificationStatus],
    expected_calls: int,
    expected_state: TutorState,
) -> None:
    user, session, db = reply_context("numeric")
    monkeypatch.setattr(
        tutor_api,
        "ai",
        FakeTutorAI(TutorTurn(message="Model response", state=TutorState.VERIFY, likely_correct=True)),
    )
    requests: list[object] = []

    def fake_verify(request: object) -> VerificationResult:
        requests.append(request)
        return VerificationResult(statuses.pop(0))

    monkeypatch.setattr(tutor_api, "verify", fake_verify)

    response = reply(user, session, db)

    assert len(requests) == expected_calls
    if expected_calls == 2:
        assert requests[0] is requests[1]
    assert response.tutor.state is expected_state
    assert session.current_state == response.tutor.state.value


def test_hint_request_skips_deterministic_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, session, db = reply_context("numeric")
    fake_ai = FakeTutorAI(TutorTurn(message="Hint", state=TutorState.HINT_1))
    monkeypatch.setattr(tutor_api, "ai", fake_ai)
    monkeypatch.setattr(
        tutor_api,
        "verify",
        lambda _request: pytest.fail("hint request must not verify"),
    )

    response = reply(user, session, db, intent=TutorReplyIntent.HINT_REQUEST)

    assert fake_ai.intents == [TutorReplyIntent.HINT_REQUEST]
    assert response.tutor.state is TutorState.HINT_1


def test_no_family_preserves_model_derived_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, session, db = reply_context(None)
    monkeypatch.setattr(
        tutor_api,
        "ai",
        FakeTutorAI(TutorTurn(message="Model response", state=TutorState.HINT_1, likely_correct=False)),
    )
    monkeypatch.setattr(
        tutor_api,
        "verify",
        lambda _request: pytest.fail("no-family session must not verify"),
    )

    response = reply(user, session, db)

    assert response.tutor.state is TutorState.HINT_1
    assert session.current_state == TutorState.HINT_1.value


@pytest.mark.parametrize(
    ("current_state", "status", "expected_state", "expected_hint_level"),
    [
        (
            TutorState.HINT_1,
            VerificationStatus.INCORRECT,
            TutorState.HINT_2,
            2,
        ),
        (
            TutorState.HINT_2,
            VerificationStatus.INCORRECT,
            TutorState.EXPLAIN_STEP,
            0,
        ),
        (
            TutorState.HINT_1,
            VerificationStatus.CORRECT,
            TutorState.VERIFY,
            0,
        ),
        (
            TutorState.HINT_2,
            VerificationStatus.CORRECT,
            TutorState.VERIFY,
            0,
        ),
    ],
)
def test_hint_attempt_states_follow_deterministic_verdict_transitions(
    monkeypatch: pytest.MonkeyPatch,
    current_state: TutorState,
    status: VerificationStatus,
    expected_state: TutorState,
    expected_hint_level: int,
) -> None:
    user, session, db = reply_context("numeric", current_state=current_state)
    monkeypatch.setattr(
        tutor_api,
        "ai",
        FakeTutorAI(
            TutorTurn(
                message="Model response",
                state=TutorState.VERIFY,
                likely_correct=status is VerificationStatus.INCORRECT,
            )
        ),
    )
    monkeypatch.setattr(
        tutor_api,
        "verify",
        lambda _request: VerificationResult(status),
    )

    response = reply(user, session, db)

    assert response.tutor.state is expected_state
    assert response.tutor.hint_level == expected_hint_level
    assert session.current_state == response.tutor.state.value


def test_authoritative_non_complete_state_is_leakage_guarded_after_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, session, db = reply_context("numeric")
    session.internal_expected_answer = "SECRET_FINAL_ANSWER_42"
    monkeypatch.setattr(
        tutor_api,
        "ai",
        FakeTutorAI(
            TutorTurn(
                message="The final answer is SECRET_FINAL_ANSWER_42.",
                state=TutorState.COMPLETE,
                likely_correct=True,
            )
        ),
    )
    monkeypatch.setattr(
        tutor_api,
        "verify",
        lambda _request: VerificationResult(VerificationStatus.INCORRECT),
    )

    response = reply(user, session, db)

    assert response.tutor.state is TutorState.HINT_1
    assert session.current_state == response.tutor.state.value
    assert session.internal_expected_answer not in response.tutor.message

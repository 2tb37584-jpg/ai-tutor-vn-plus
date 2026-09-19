from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api import tutor as tutor_api
from app.models import Student, TutorMessage, TutorSession, User
from app.schemas.tutor import (
    TutorReplyIntent,
    TutorReplyRequest,
    TutorState,
    TutorTransitionEvent,
    TutorTransitionInput,
    TutorTurn,
)
from app.services.tutor_ai import TutorAI
from app.services.tutor_state import InvalidTutorTransition, transition_tutor_state


def _demo_tutor() -> TutorAI:
    tutor = TutorAI.__new__(TutorAI)
    tutor.client = None
    return tutor


def test_reply_intent_defaults_to_attempt() -> None:
    request = TutorReplyRequest(session_id=1, student_message="x = 4")

    assert request.intent is TutorReplyIntent.ATTEMPT


def test_hint_request_intent_parses() -> None:
    request = TutorReplyRequest(
        session_id=1,
        student_message="Cho em gợi ý",
        intent="hint_request",
    )

    assert request.intent is TutorReplyIntent.HINT_REQUEST


def test_unknown_reply_intent_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TutorReplyRequest(session_id=1, student_message="Help", intent="unknown")


@pytest.mark.parametrize(
    ("current_state", "expected_state"),
    [
        (TutorState.ASK_ATTEMPT, TutorState.HINT_1),
        (TutorState.HINT_1, TutorState.HINT_2),
        (TutorState.HINT_2, TutorState.EXPLAIN_STEP),
    ],
)
def test_hint_requested_transition(current_state: TutorState, expected_state: TutorState) -> None:
    result = transition_tutor_state(
        TutorTransitionInput(
            state=current_state,
            event=TutorTransitionEvent.HINT_REQUESTED,
        )
    )

    assert result is expected_state


@pytest.mark.parametrize(
    "current_state",
    [
        TutorState.DIAGNOSE,
        TutorState.EXPLAIN_STEP,
        TutorState.VERIFY,
        TutorState.TRANSFER,
        TutorState.COMPLETE,
    ],
)
def test_unsupported_hint_transition_fails(current_state: TutorState) -> None:
    with pytest.raises(InvalidTutorTransition):
        transition_tutor_state(
            TutorTransitionInput(
                state=current_state,
                event=TutorTransitionEvent.HINT_REQUESTED,
            )
        )


def test_existing_attempt_transition_is_unchanged() -> None:
    result = transition_tutor_state(
        TutorTransitionInput(
            state=TutorState.ASK_ATTEMPT,
            event=TutorTransitionEvent.ATTEMPT_INCORRECT,
        )
    )

    assert result is TutorState.HINT_1


@pytest.mark.parametrize(
    ("current_state", "expected_state", "expected_level"),
    [
        (TutorState.ASK_ATTEMPT, TutorState.HINT_1, 1),
        (TutorState.HINT_1, TutorState.HINT_2, 2),
        (TutorState.HINT_2, TutorState.EXPLAIN_STEP, 3),
    ],
)
def test_no_client_hint_request_progression(
    current_state: TutorState,
    expected_state: TutorState,
    expected_level: int,
) -> None:
    turn = _demo_tutor().continue_turn(
        "problem",
        "algebra.linear_equation",
        [],
        "Cho em gợi ý",
        current_state=current_state,
        intent=TutorReplyIntent.HINT_REQUEST,
    )

    assert turn.state is expected_state
    assert turn.hint_level == expected_level


@pytest.mark.parametrize("likely_correct", [None, False, True])
def test_model_signals_cannot_override_or_double_advance_hint_target(
    likely_correct: bool | None,
) -> None:
    raw_turn = TutorTurn(
        message="Generated hint",
        state=TutorState.COMPLETE,
        likely_correct=likely_correct,
    )
    captured: dict[str, object] = {}

    def parse(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(output_parsed=raw_turn)

    tutor = TutorAI.__new__(TutorAI)
    tutor.settings = SimpleNamespace(openai_model="test-model")
    tutor.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))

    result = tutor.continue_turn(
        "problem",
        "skill",
        [],
        "help",
        current_state=TutorState.ASK_ATTEMPT,
        intent=TutorReplyIntent.HINT_REQUEST,
    )

    assert result.state is TutorState.HINT_1
    assert result.hint_level == 1
    prompt = captured["input"][1]["content"]
    assert "Current tutor state: hint_1" in prompt
    assert "Current tutor state: ask_attempt" not in prompt
    assert "target state hint_1" in prompt
    assert TutorAI._generation_policy(TutorState.HINT_1) in prompt


def test_omitted_ai_intent_keeps_attempt_semantics() -> None:
    turn = TutorTurn(message="Try again", likely_correct=False)
    tutor = TutorAI.__new__(TutorAI)
    tutor.settings = SimpleNamespace(openai_model="test-model")
    tutor.client = SimpleNamespace(
        responses=SimpleNamespace(
            parse=lambda **_: SimpleNamespace(output_parsed=turn)
        )
    )

    result = tutor.continue_turn(
        "problem",
        "skill",
        [],
        "attempt",
        current_state=TutorState.ASK_ATTEMPT,
    )

    assert result.state is TutorState.HINT_1


class FakeDatabase:
    def __init__(self, student: Student, session: TutorSession) -> None:
        self.student = student
        self.session = session
        self.messages: list[TutorMessage] = []
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
        self.received_intents: list[TutorReplyIntent] = []

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
        self.received_intents.append(intent)
        state = (
            TutorState.HINT_1
            if intent is TutorReplyIntent.HINT_REQUEST
            else current_state
        )
        return TutorTurn(message="Next question", state=state, hint_level=1)


def _api_context(current_state: TutorState) -> tuple[User, FakeDatabase]:
    user = User(id=1, email="parent@example.com", password_hash="hash")
    student = Student(id=2, owner_id=1, display_name="Student", grade=8)
    session = TutorSession(
        id=3,
        student_id=student.id,
        normalized_problem="Solve x + 1 = 2",
        primary_skill="algebra.linear_equation",
        current_state=current_state.value,
        internal_expected_answer="1",
    )
    return user, FakeDatabase(student, session)


def test_api_passes_hint_intent_and_persists_returned_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, db = _api_context(TutorState.ASK_ATTEMPT)
    fake_ai = FakeTutorAI()
    monkeypatch.setattr(tutor_api, "ai", fake_ai)

    response = tutor_api.tutor_reply(
        TutorReplyRequest(
            session_id=3,
            student_message="Cho em gợi ý",
            intent=TutorReplyIntent.HINT_REQUEST,
        ),
        user,
        db,
    )

    assert fake_ai.received_intents == [TutorReplyIntent.HINT_REQUEST]
    assert response.tutor.state is TutorState.HINT_1
    assert db.session.current_state == "hint_1"
    assert [message.role for message in db.messages] == ["user", "assistant"]
    assert db.commits == 1


def test_api_request_without_intent_remains_an_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, db = _api_context(TutorState.ASK_ATTEMPT)
    fake_ai = FakeTutorAI()
    monkeypatch.setattr(tutor_api, "ai", fake_ai)

    tutor_api.tutor_reply(
        TutorReplyRequest(session_id=3, student_message="x = 1"),
        user,
        db,
    )

    assert fake_ai.received_intents == [TutorReplyIntent.ATTEMPT]
    assert db.commits == 1


def test_invalid_api_hint_request_has_no_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, db = _api_context(TutorState.VERIFY)
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
    assert error.value.detail == "Hint request is unavailable in the current tutor state"
    assert fake_ai.calls == 0
    assert db.messages == []
    assert db.session.current_state == "verify"
    assert db.commits == 0

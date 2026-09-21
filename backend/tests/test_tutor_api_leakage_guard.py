import pytest

from app.api import tutor as tutor_api
from app.models import Student, TutorMessage, TutorSession, User
from app.schemas.tutor import (
    ProblemAnalysis,
    StartTutorRequest,
    TutorReplyRequest,
    TutorState,
    TutorTurn,
)


class FakeDatabase:
    def __init__(self, student: Student) -> None:
        self.student = student
        self.session: TutorSession | None = None
        self.messages: list[TutorMessage] = []

    def get(self, model: type[object], record_id: int) -> object | None:
        if model is Student and record_id == self.student.id:
            return self.student
        if model is TutorSession and self.session is not None and record_id == self.session.id:
            return self.session
        return None

    def add(self, record: object) -> None:
        if isinstance(record, TutorSession):
            record.id = 1
            self.session = record
        elif isinstance(record, TutorMessage):
            self.messages.append(record)

    def flush(self) -> None:
        pass

    def commit(self) -> None:
        pass

    def scalars(self, _statement: object) -> list[TutorMessage]:
        return self.messages.copy()


class FakeTutorAI:
    def __init__(self, first_turn: TutorTurn, reply_turn: TutorTurn | None = None) -> None:
        self.first = first_turn
        self.reply = reply_turn
        self.analysis = ProblemAnalysis(normalized_problem="Solve x = 2", expected_answer="x = 2")
        self.received_state: TutorState | None = None

    def analyze_problem(self, problem_text: str, image_data_url: str | None = None) -> ProblemAnalysis:
        return self.analysis

    def first_turn(self, analysis: ProblemAnalysis, grade: int | None) -> TutorTurn:
        return self.first

    def continue_turn(
        self,
        problem: str,
        skill: str,
        history: list[tuple[str, str]],
        student_message: str,
        *,
        current_state: TutorState,
    ) -> TutorTurn:
        self.received_state = current_state
        assert self.reply is not None
        return self.reply


def start_context(monkeypatch: pytest.MonkeyPatch, fake_ai: FakeTutorAI) -> tuple[User, FakeDatabase]:
    monkeypatch.setattr(tutor_api, "ai", fake_ai)
    user = User(id=1, email="parent@example.com", password_hash="hash")
    student = Student(id=2, owner_id=1, display_name="Student", grade=6)
    return user, FakeDatabase(student)


def start_session(user: User, db: FakeDatabase):
    return tutor_api.start_tutor(
        StartTutorRequest(student_id=2, problem_text="Solve x = 2"), user=user, db=db
    )


def assistant_messages(db: FakeDatabase) -> list[str]:
    return [message.content for message in db.messages if message.role == "assistant"]


def test_start_blocks_textual_leak_before_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    leaked = TutorTurn(
        message="Vậy x=2.",
        state=TutorState.HINT_1,
        hint_level=1,
        likely_correct=False,
        skill_tags=["algebra.linear_equation"],
        reveal_final_answer=False,
    )
    user, db = start_context(monkeypatch, FakeTutorAI(leaked))

    response = start_session(user, db)

    assert response.tutor.message == tutor_api._SAFE_TUTOR_FALLBACK
    assert response.tutor.reveal_final_answer is False
    assert response.tutor.state is TutorState.HINT_1
    assert response.tutor.hint_level == 1
    assert response.tutor.likely_correct is False
    assert response.tutor.skill_tags == ["algebra.linear_equation"]
    assert assistant_messages(db) == [tutor_api._SAFE_TUTOR_FALLBACK]
    assert "x=2" not in assistant_messages(db)[0]
    assert db.session is not None
    assert db.session.current_state == "hint_1"
    assert db.session.internal_expected_answer == "x = 2"


def test_start_blocks_true_model_self_report(monkeypatch: pytest.MonkeyPatch) -> None:
    reported = TutorTurn(message="A seemingly safe question", reveal_final_answer=True)
    user, db = start_context(monkeypatch, FakeTutorAI(reported))

    response = start_session(user, db)

    assert response.tutor.message == tutor_api._SAFE_TUTOR_FALLBACK
    assert response.tutor.reveal_final_answer is False
    assert assistant_messages(db) == [tutor_api._SAFE_TUTOR_FALLBACK]


def test_reply_uses_persisted_answer_and_preserves_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = TutorTurn(
        message="Đáp án là Hà Nội.",
        state=TutorState.HINT_2,
        hint_level=2,
        likely_correct=False,
        skill_tags=["algebra.linear_equation"],
    )
    fake_ai = FakeTutorAI(TutorTurn(message="First question", state=TutorState.ASK_ATTEMPT), reply)
    user, db = start_context(monkeypatch, fake_ai)
    start_session(user, db)
    assert db.session is not None
    db.session.internal_expected_answer = "Hà Nội"

    response = tutor_api.tutor_reply(TutorReplyRequest(session_id=1, student_message="My try"), user, db)

    assert fake_ai.received_state is TutorState.ASK_ATTEMPT
    assert response.tutor.message == tutor_api._SAFE_TUTOR_FALLBACK
    assert response.tutor.reveal_final_answer is False
    assert response.tutor.state is TutorState.HINT_2
    assert response.tutor.hint_level == 2
    assert response.tutor.likely_correct is False
    assert response.tutor.skill_tags == ["algebra.linear_equation"]
    assert db.session.current_state == "hint_2"
    assert assistant_messages(db) == ["First question", tutor_api._SAFE_TUTOR_FALLBACK]
    assert "Hà Nội" not in assistant_messages(db)[-1]


def test_safe_reply_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    safe = TutorTurn(message="Which operation would you use?", state=TutorState.HINT_1, hint_level=1)
    fake_ai = FakeTutorAI(TutorTurn(message="First question", state=TutorState.ASK_ATTEMPT), safe)
    user, db = start_context(monkeypatch, fake_ai)
    start_session(user, db)

    response = tutor_api.tutor_reply(TutorReplyRequest(session_id=1, student_message="My try"), user, db)

    assert response.tutor is safe
    assert assistant_messages(db)[-1] == safe.message


def test_start_allows_instructional_single_symbol_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    safe = TutorTurn(
        message="Hãy gom các hạng tử chứa x.",
        state=TutorState.HINT_1,
        hint_level=1,
        reveal_final_answer=False,
    )
    fake_ai = FakeTutorAI(safe)
    fake_ai.analysis = ProblemAnalysis(
        normalized_problem="Thu gọn 2x + 5 - x - 5.",
        expected_answer="x",
    )
    user, db = start_context(monkeypatch, fake_ai)

    response = start_session(user, db)

    assert response.tutor is safe
    assert response.tutor.reveal_final_answer is False
    assert assistant_messages(db) == [safe.message]
    assert db.session is not None
    assert db.session.internal_expected_answer == "x"


def test_start_blocks_direct_single_symbol_disclosure(monkeypatch: pytest.MonkeyPatch) -> None:
    leaked = TutorTurn(
        message="Đáp án là x.",
        state=TutorState.HINT_1,
        hint_level=1,
        likely_correct=False,
        skill_tags=["algebra.expression.combine_like_terms"],
        reveal_final_answer=False,
    )
    fake_ai = FakeTutorAI(leaked)
    fake_ai.analysis = ProblemAnalysis(
        normalized_problem="Thu gọn 2x + 5 - x - 5.",
        expected_answer="x",
    )
    user, db = start_context(monkeypatch, fake_ai)

    response = start_session(user, db)

    assert response.tutor.message == tutor_api._SAFE_TUTOR_FALLBACK
    assert response.tutor.reveal_final_answer is False
    assert response.tutor.state is TutorState.HINT_1
    assert response.tutor.hint_level == 1
    assert response.tutor.likely_correct is False
    assert response.tutor.skill_tags == ["algebra.expression.combine_like_terms"]
    assert assistant_messages(db) == [tutor_api._SAFE_TUTOR_FALLBACK]
    assert "Đáp án là x" not in assistant_messages(db)[0]


def test_complete_reply_bypasses_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    complete = TutorTurn(message="Vậy x=2.", state=TutorState.COMPLETE, reveal_final_answer=True)
    fake_ai = FakeTutorAI(TutorTurn(message="First question", state=TutorState.ASK_ATTEMPT), complete)
    user, db = start_context(monkeypatch, fake_ai)
    start_session(user, db)

    response = tutor_api.tutor_reply(TutorReplyRequest(session_id=1, student_message="My try"), user, db)

    assert response.tutor is complete
    assert response.tutor.reveal_final_answer is True
    assert assistant_messages(db)[-1] == "Vậy x=2."

import pytest
import app.services.question_recommender as recommender
from fastapi import HTTPException

from app.api import tutor as tutor_api
from app.models import Student, TutorMessage, TutorSession, User
from app.schemas.tutor import (
    ProblemAnalysis,
    StartTutorRequest,
    TutorReplyRequest,
    TutorState,
    TutorTurn,
)
import app.services.question_bank as question_bank
from app.services.question_bank import get_transfer_question_for_skill
from app.services.verifier import VerificationResult, VerificationStatus


class FakeDatabase:
    def __init__(self, student: Student) -> None:
        self.student = student
        self.sessions: dict[int, TutorSession] = {}
        self.messages: list[TutorMessage] = []
        self.commits = 0

    def get(self, model: type[object], record_id: int) -> object | None:
        if model is Student:
            return self.student if record_id == self.student.id else None
        if model is TutorSession:
            return self.sessions.get(record_id)
        return None

    def add(self, record: object) -> None:
        if isinstance(record, TutorSession):
            record.id = len(self.sessions) + 1
            self.sessions[record.id] = record
        elif isinstance(record, TutorMessage):
            self.messages.append(record)

    def flush(self) -> None:
        pass

    def commit(self) -> None:
        self.commits += 1

    def scalars(self, _statement: object) -> list[TutorMessage]:
        return self.messages.copy()


class FakeTutorAI:
    def __init__(
        self,
        reply_states: list[TutorState],
        first_turn_state: TutorState = TutorState.ASK_ATTEMPT,
        analysis_skills: list[str] | None = None,
    ) -> None:
        self.reply_states = iter(reply_states)
        self.first_turn_state = first_turn_state
        self.analysis_skills = analysis_skills or ["algebra.linear_equation"]
        self.received_states: list[TutorState] = []
        self.continue_calls = 0

    def analyze_problem(self, problem_text: str, image_data_url: str | None = None) -> ProblemAnalysis:
        return ProblemAnalysis(normalized_problem=problem_text, skills=self.analysis_skills)

    def first_turn(self, analysis: ProblemAnalysis, grade: int | None) -> TutorTurn:
        return TutorTurn(message="First question", state=self.first_turn_state)

    def continue_turn(
        self,
        problem: str,
        skill: str,
        history: list[tuple[str, str]],
        student_message: str,
        *,
        current_state: TutorState,
    ) -> TutorTurn:
        self.continue_calls += 1
        self.received_states.append(current_state)
        return TutorTurn(message="Next question", state=next(self.reply_states))


def tutor_context() -> tuple[User, Student, FakeDatabase]:
    user = User(id=1, email="parent@example.com", password_hash="hash")
    student = Student(id=1, owner_id=user.id, display_name="Student", grade=6)
    return user, student, FakeDatabase(student)


def start_session(user: User, db: FakeDatabase) -> int:
    response = tutor_api.start_tutor(
        StartTutorRequest(student_id=user.id, problem_text="Solve x + 1 = 2"),
        user=user,
        db=db,
    )
    return response.session_id


def test_start_persists_first_turn_state(monkeypatch: pytest.MonkeyPatch) -> None:
    user, _, db = tutor_context()
    fake_ai = FakeTutorAI([])
    monkeypatch.setattr(tutor_api, "ai", fake_ai)

    session_id = start_session(user, db)

    assert db.sessions[session_id].current_state == "ask_attempt"


def test_start_persists_state_returned_by_tutor_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    user, _, db = tutor_context()
    fake_ai = FakeTutorAI([], first_turn_state=TutorState.HINT_1)
    monkeypatch.setattr(tutor_api, "ai", fake_ai)

    session_id = start_session(user, db)

    assert db.sessions[session_id].current_state == "hint_1"


def test_replies_pass_and_persist_state_across_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    user, _, db = tutor_context()
    fake_ai = FakeTutorAI(
        [TutorState.HINT_1, TutorState.HINT_2],
        analysis_skills=["unknown.skill"],
    )
    monkeypatch.setattr(tutor_api, "ai", fake_ai)
    session_id = start_session(user, db)

    assert db.sessions[session_id].verification_family is None

    tutor_api.tutor_reply(TutorReplyRequest(session_id=session_id, student_message="x = 3"), user, db)
    assert db.sessions[session_id].current_state == "hint_1"

    tutor_api.tutor_reply(TutorReplyRequest(session_id=session_id, student_message="x = 4"), user, db)

    assert fake_ai.received_states == [TutorState.ASK_ATTEMPT, TutorState.HINT_1]
    assert db.sessions[session_id].current_state == "hint_2"


def test_invalid_persisted_state_fails_without_calling_tutor_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    user, _, db = tutor_context()
    fake_ai = FakeTutorAI([TutorState.HINT_1])
    monkeypatch.setattr(tutor_api, "ai", fake_ai)
    session_id = start_session(user, db)
    db.sessions[session_id].current_state = "not-a-state"

    with pytest.raises(HTTPException) as error:
        tutor_api.tutor_reply(TutorReplyRequest(session_id=session_id, student_message="Help"), user, db)

    assert error.value.status_code == 500
    assert fake_ai.continue_calls == 0


def test_entering_transfer_selects_and_reuses_exact_factorization_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, student, db = tutor_context()
    session = TutorSession(
        id=1,
        student_id=student.id,
        primary_skill="algebra.factorization",
        current_state=TutorState.VERIFY.value,
        internal_expected_answer="1",
        verification_family="numeric",
    )
    db.sessions[session.id] = session
    fake_ai = FakeTutorAI([TutorState.TRANSFER, TutorState.TRANSFER])
    monkeypatch.setattr(tutor_api, "ai", fake_ai)
    monkeypatch.setattr(
        tutor_api,
        "verify",
        lambda _request: VerificationResult(VerificationStatus.CORRECT),
    )
    monkeypatch.setattr(
        recommender,
        "recommend_next_question",
        lambda *args, **kwargs: pytest.fail(
            "transfer entry must not invoke the next-best-question recommender"
        ),
    )
    selected_skills: list[str] = []

    def select_once(skill_code: str):
        selected_skills.append(skill_code)
        return get_transfer_question_for_skill(skill_code)

    monkeypatch.setattr(tutor_api, "get_transfer_question_for_skill", select_once)

    tutor_api.tutor_reply(
        TutorReplyRequest(session_id=session.id, student_message="first"),
        user,
        db,
    )

    assert session.current_state == TutorState.TRANSFER.value
    assert session.transfer_question_id == "g8alg.factorization.001"
    assert selected_skills == ["algebra.factorization"]

    tutor_api.tutor_reply(
        TutorReplyRequest(session_id=session.id, student_message="later"),
        user,
        db,
    )

    assert session.current_state == TutorState.TRANSFER.value
    assert session.transfer_question_id == "g8alg.factorization.001"
    assert selected_skills == ["algebra.factorization"]


@pytest.mark.parametrize(
    ("skill_code", "expected_id"),
    [
        ("algebra.rational_expression.domain", "g8alg.rational-expression-domain.001"),
        ("arithmetic.signed_number_operations", "g8alg.signed-number-operations.001"),
    ],
)
def test_transfer_question_selection_is_exact_and_declaration_ordered(
    skill_code: str,
    expected_id: str,
) -> None:
    item = get_transfer_question_for_skill(skill_code)

    assert item is not None
    assert item.id == expected_id
    assert item.skill_code == skill_code


def test_transfer_question_selection_excludes_non_mastery_supported_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    non_mastery_item = question_bank.QuestionBankItem(
        id="g8alg.non-mastery-numeric.001",
        skill_code="general.non_mastery_numeric",
        problem_text="non-mastery item",
        verification_reference="1",
        expected_answer="1",
        verification_family="numeric",
        difficulty=1,
    )
    monkeypatch.setattr(question_bank, "_QUESTION_BANK", (non_mastery_item,))

    assert get_transfer_question_for_skill("general.non_mastery_numeric") is None


@pytest.mark.parametrize(
    "skill_code",
    [None, "algebra.rational_expression.simplify", "algebra.factorization.neighbor"],
)
def test_transfer_question_selection_has_no_missing_or_related_skill_fallback(
    skill_code: str | None,
) -> None:
    session = TutorSession(
        student_id=1,
        primary_skill=skill_code,
        current_state=TutorState.VERIFY.value,
    )

    tutor_api._persist_transfer_question_id_on_entry(
        session,
        TutorState.VERIFY,
        TutorState.TRANSFER,
    )

    assert session.transfer_question_id is None


def test_transfer_question_selection_preserves_existing_id() -> None:
    session = TutorSession(
        student_id=1,
        primary_skill="algebra.factorization",
        transfer_question_id="g8alg.factorization.001",
        current_state=TutorState.VERIFY.value,
    )

    tutor_api._persist_transfer_question_id_on_entry(
        session,
        TutorState.VERIFY,
        TutorState.TRANSFER,
    )

    assert session.transfer_question_id == "g8alg.factorization.001"


def test_transfer_entry_does_not_complete_or_update_mastery() -> None:
    session = TutorSession(
        student_id=1,
        primary_skill="algebra.factorization",
        current_state=TutorState.VERIFY.value,
    )

    tutor_api._persist_transfer_question_id_on_entry(
        session,
        TutorState.VERIFY,
        TutorState.TRANSFER,
    )

    assert session.current_state == TutorState.VERIFY.value
    assert session.transfer_question_id == "g8alg.factorization.001"

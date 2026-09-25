import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api import tutor as tutor_api
from app.models import Student, TutorMessage, TutorSession, User
from app.schemas.tutor import (
    ProblemAnalysis,
    StartAuthoredTutorRequest,
    StartAuthoredTutorResponse,
    TutorState,
    TutorTurn,
)
from app.services.question_bank import get_question


class FakeDatabase:
    def __init__(self, student: Student) -> None:
        self.student = student
        self.sessions: list[TutorSession] = []
        self.messages: list[TutorMessage] = []
        self.flushes = 0
        self.commits = 0

    def get(self, model: type[object], record_id: int) -> object | None:
        if model is Student and record_id == self.student.id:
            return self.student
        return None

    def add(self, record: object) -> None:
        if isinstance(record, TutorSession):
            record.id = len(self.sessions) + 1
            self.sessions.append(record)
        elif isinstance(record, TutorMessage):
            self.messages.append(record)

    def flush(self) -> None:
        self.flushes += 1

    def commit(self) -> None:
        self.commits += 1


class FakeTutorAI:
    def __init__(self, first_turn: TutorTurn) -> None:
        self.first_turn_result = first_turn
        self.analyze_calls = 0
        self.first_turn_analysis: ProblemAnalysis | None = None

    def analyze_problem(self, problem_text: str, image_data_url: str | None = None) -> ProblemAnalysis:
        self.analyze_calls += 1
        raise AssertionError("authored start must not call analyze_problem")

    def first_turn(self, analysis: ProblemAnalysis, grade: int | None) -> TutorTurn:
        self.first_turn_analysis = analysis
        return self.first_turn_result


def tutor_context(*, owner_id: int = 1) -> tuple[User, Student, FakeDatabase]:
    user = User(id=1, email="parent@example.com", password_hash="hash")
    student = Student(id=1, owner_id=owner_id, display_name="Student", grade=8)
    return user, student, FakeDatabase(student)


def test_authored_start_uses_trusted_item_and_learner_safe_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, student, db = tutor_context()
    item = get_question("g8alg.factorization.001")
    assert item is not None
    fake_ai = FakeTutorAI(TutorTurn(message="First question", state=TutorState.ASK_ATTEMPT))
    monkeypatch.setattr(tutor_api, "ai", fake_ai)

    response = tutor_api.start_authored_tutor(
        StartAuthoredTutorRequest(student_id=student.id, question_id=item.id),
        user=user,
        db=db,
    )

    assert len(db.sessions) == 1
    session = db.sessions[0]
    assert session.student_id == student.id
    assert session.normalized_problem == item.problem_text
    assert session.primary_skill == item.skill_code
    assert session.internal_expected_answer == item.expected_answer
    assert session.verification_family == item.verification_family
    assert session.authored_question_id == item.id
    assert session.transfer_question_id is None
    assert fake_ai.analyze_calls == 0
    assert fake_ai.first_turn_analysis is not None
    assert fake_ai.first_turn_analysis.normalized_problem == item.problem_text
    assert fake_ai.first_turn_analysis.skills == [item.skill_code]
    assert fake_ai.first_turn_analysis.expected_answer == item.expected_answer
    assert fake_ai.first_turn_analysis.confidence == 1.0

    serialized = StartAuthoredTutorResponse.model_validate(response).model_dump(mode="json")
    assert serialized["question"] == {
        "question_id": item.id,
        "skill_code": item.skill_code,
        "problem_text": item.problem_text,
        "difficulty": item.difficulty,
    }
    serialized_text = str(serialized)
    assert "expected_answer" not in serialized_text
    assert "verification_reference" not in serialized_text
    assert "verification_family" not in serialized_text


def test_authored_start_unknown_question_fails_before_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, student, db = tutor_context()
    fake_ai = FakeTutorAI(TutorTurn(message="unused"))
    monkeypatch.setattr(tutor_api, "ai", fake_ai)

    with pytest.raises(HTTPException) as error:
        tutor_api.start_authored_tutor(
            StartAuthoredTutorRequest(student_id=student.id, question_id="unknown.question.999"),
            user=user,
            db=db,
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Question not found"
    assert db.sessions == []
    assert db.messages == []
    assert db.flushes == 0
    assert db.commits == 0
    assert fake_ai.analyze_calls == 0
    assert fake_ai.first_turn_analysis is None


def test_authored_start_enforces_student_ownership() -> None:
    user, student, db = tutor_context(owner_id=2)

    with pytest.raises(HTTPException) as error:
        tutor_api.start_authored_tutor(
            StartAuthoredTutorRequest(student_id=student.id, question_id="g8alg.factorization.001"),
            user=user,
            db=db,
        )

    assert error.value.status_code == 404
    assert db.sessions == []
    assert db.messages == []
    assert db.flushes == 0
    assert db.commits == 0


@pytest.mark.parametrize("extra_field", ["problem_text", "expected_answer", "verification_family"])
def test_authored_start_rejects_client_authority_overrides(extra_field: str) -> None:
    payload = {"student_id": 1, "question_id": "g8alg.factorization.001", extra_field: "client value"}

    with pytest.raises(ValidationError):
        StartAuthoredTutorRequest.model_validate(payload)


def test_authored_start_applies_answer_leakage_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, student, db = tutor_context()
    item = get_question("g8alg.factorization.001")
    assert item is not None
    monkeypatch.setattr(
        tutor_api,
        "ai",
        FakeTutorAI(
            TutorTurn(
                message=item.expected_answer,
                state=TutorState.ASK_ATTEMPT,
                reveal_final_answer=False,
            )
        ),
    )

    response = tutor_api.start_authored_tutor(
        StartAuthoredTutorRequest(student_id=student.id, question_id=item.id),
        user=user,
        db=db,
    )

    assert response.tutor.message == tutor_api._SAFE_TUTOR_FALLBACK
    assert db.messages[-1].content == tutor_api._SAFE_TUTOR_FALLBACK
    assert db.sessions[0].current_state == TutorState.ASK_ATTEMPT.value

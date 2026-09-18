import pytest

from app.api import tutor as tutor_api
from app.models import Student, TutorMessage, TutorSession, User
from app.schemas.tutor import ProblemAnalysis, StartTutorRequest, StartTutorResponse, TutorState, TutorTurn


class FakeDatabase:
    def __init__(self, student: Student) -> None:
        self.student = student
        self.session: TutorSession | None = None
        self.messages: list[TutorMessage] = []

    def get(self, model: type[object], record_id: int) -> object | None:
        if model is Student and record_id == self.student.id:
            return self.student
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


class FakeTutorAI:
    def __init__(self, analysis: ProblemAnalysis) -> None:
        self.analysis = analysis
        self.first_turn_analysis: ProblemAnalysis | None = None

    def analyze_problem(self, problem_text: str, image_data_url: str | None = None) -> ProblemAnalysis:
        return self.analysis

    def first_turn(self, analysis: ProblemAnalysis, grade: int | None) -> TutorTurn:
        self.first_turn_analysis = analysis
        return TutorTurn(message="What would you try first?", state=TutorState.ASK_ATTEMPT)


def test_start_exposes_only_public_analysis_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    internal_analysis = ProblemAnalysis(
        normalized_problem="Solve x + 1 = 2",
        subject="math",
        grade_band="middle",
        skills=["algebra.linear_equation"],
        prerequisites=["arithmetic.addition"],
        expected_answer="SECRET_FINAL_ANSWER_42",
        verification_notes="SECRET_INTERNAL_NOTE",
        confidence=0.9,
    )
    fake_ai = FakeTutorAI(internal_analysis)
    monkeypatch.setattr(tutor_api, "ai", fake_ai)
    user = User(id=1, email="parent@example.com", password_hash="hash")
    student = Student(id=2, owner_id=1, display_name="Student", grade=6)
    db = FakeDatabase(student)

    assert internal_analysis.expected_answer == "SECRET_FINAL_ANSWER_42"
    assert internal_analysis.verification_notes == "SECRET_INTERNAL_NOTE"

    response = tutor_api.start_tutor(
        StartTutorRequest(student_id=2, problem_text="Solve x + 1 = 2"), user=user, db=db
    )
    serialized = StartTutorResponse.model_validate(response).model_dump(mode="json")

    assert db.session is not None
    assert db.session.internal_expected_answer == "SECRET_FINAL_ANSWER_42"
    assert db.session.current_state == "ask_attempt"
    assert fake_ai.first_turn_analysis is internal_analysis
    assert internal_analysis.expected_answer == "SECRET_FINAL_ANSWER_42"
    assert internal_analysis.verification_notes == "SECRET_INTERNAL_NOTE"
    assert set(serialized["analysis"]) == {
        "normalized_problem",
        "subject",
        "grade_band",
        "skills",
        "prerequisites",
        "confidence",
    }
    assert "expected_answer" not in serialized["analysis"]
    assert "verification_notes" not in serialized["analysis"]
    assert "internal_expected_answer" not in str(serialized)
    assert "SECRET_FINAL_ANSWER_42" not in str(serialized)
    assert "SECRET_INTERNAL_NOTE" not in str(serialized)
    assert serialized["analysis"]["normalized_problem"] == "Solve x + 1 = 2"
    assert serialized["analysis"]["skills"] == ["algebra.linear_equation"]
    assert serialized["analysis"]["confidence"] == 0.9

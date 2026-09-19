import pytest
from fastapi import HTTPException

from app.api.tutor import save_attempt
from app.models import Attempt, Student, TutorSession, User
from app.schemas.tutor import AttemptRequest


class FakeDatabase:
    def __init__(
        self,
        student: Student | None,
        session: TutorSession | None = None,
    ) -> None:
        self.student = student
        self.session = session
        self.added: list[object] = []
        self.commits = 0

    def get(self, model: type[object], record_id: int) -> object | None:
        if model is Student and self.student is not None and record_id == self.student.id:
            return self.student
        if model is TutorSession and self.session is not None and record_id == self.session.id:
            return self.session
        return None

    def add(self, record: object) -> None:
        self.added.append(record)

    def commit(self) -> None:
        self.commits += 1


def user() -> User:
    return User(id=1, email="parent@example.com", password_hash="hash")


def student(owner_id: int = 1) -> Student:
    return Student(id=2, owner_id=owner_id, display_name="Student", grade=8)


@pytest.mark.parametrize("correct", [True, False])
def test_attempt_logs_client_claim_without_mutating_mastery(correct: bool) -> None:
    db = FakeDatabase(student())
    payload = AttemptRequest(
        student_id=2,
        skill_code="algebra.linear_equation",
        correct=correct,
    )

    response = save_attempt(payload, user(), db)

    assert len(db.added) == 1
    assert isinstance(db.added[0], Attempt)
    assert db.added[0].correct is correct
    assert db.commits == 1
    assert response.ok is True
    assert response.mastery_updated is False
    assert response.mastery_reason == "client_claim_not_mastery_eligible"
    assert response.mastery_before is None
    assert response.mastery_after is None


def test_attempt_enforces_student_ownership() -> None:
    db = FakeDatabase(student(owner_id=99))
    payload = AttemptRequest(student_id=2, skill_code="algebra.linear_equation", correct=True)

    with pytest.raises(HTTPException) as error:
        save_attempt(payload, user(), db)

    assert error.value.status_code == 404
    assert db.added == []
    assert db.commits == 0


def test_attempt_enforces_session_ownership() -> None:
    owned_student = student()
    session = TutorSession(id=3, student_id=99, normalized_problem="problem")
    db = FakeDatabase(owned_student, session)
    payload = AttemptRequest(
        student_id=2,
        session_id=3,
        skill_code="algebra.linear_equation",
        correct=True,
    )

    with pytest.raises(HTTPException) as error:
        save_attempt(payload, user(), db)

    assert error.value.status_code == 404
    assert db.added == []
    assert db.commits == 0

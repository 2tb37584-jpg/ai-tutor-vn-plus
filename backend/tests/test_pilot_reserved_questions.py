import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models import PilotEnrollment, PilotSkillAssignment, Student, User
from app.services.pilot_reserved_questions import (
    PilotReservedQuestionStateError,
    get_active_pilot_reserved_question_ids,
)


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(email="pilot@example.com", password_hash="hash")
        session.add(user)
        session.flush()
        session.add(Student(id=1, owner_id=user.id, display_name="Student", grade=8))
        session.commit()
        yield session


def add_enrollment(
    db: Session,
    *,
    phase: str = "pre",
    public_id: str = "pilot-1",
    assignment_count: int = 9,
) -> PilotEnrollment:
    enrollment = PilotEnrollment(public_id=public_id, student_id=1, phase=phase)
    db.add(enrollment)
    db.flush()
    for index in range(assignment_count):
        db.add(
            PilotSkillAssignment(
                pilot_enrollment_id=enrollment.id,
                skill_code=f"skill.{index}",
                pre_question_id=f"pre.{index}",
                learning_question_id=f"learning.{index}",
                post_question_id=f"post.{index}",
            )
        )
    db.commit()
    return enrollment


def test_no_pilot_returns_empty_tuple(db: Session) -> None:
    assert get_active_pilot_reserved_question_ids(db, student_id=1) == ()


@pytest.mark.parametrize("phase", ["pre", "intervention", "post"])
def test_each_non_terminal_phase_reserves_all_roles(db: Session, phase: str) -> None:
    add_enrollment(db, phase=phase)

    assert get_active_pilot_reserved_question_ids(db, student_id=1) == tuple(
        question_id
        for index in range(9)
        for question_id in (f"pre.{index}", f"learning.{index}", f"post.{index}")
    )


def test_completed_only_pilot_returns_empty_tuple(db: Session) -> None:
    add_enrollment(db, phase="complete")

    assert get_active_pilot_reserved_question_ids(db, student_id=1) == ()


def test_active_enrollment_wins_over_older_completed_enrollment(db: Session) -> None:
    add_enrollment(db, phase="complete", public_id="pilot-old")
    add_enrollment(db, phase="intervention", public_id="pilot-active")

    reserved = get_active_pilot_reserved_question_ids(db, student_id=1)

    assert reserved[0] == "pre.0"
    assert len(reserved) == 27


def test_persisted_ids_and_assignment_order_are_authoritative(db: Session) -> None:
    add_enrollment(db)
    assignments = list(
        db.scalars(
            select(PilotSkillAssignment).order_by(PilotSkillAssignment.id)
        )
    )
    assignments[0].pre_question_id = "persisted-pre"
    assignments[0].learning_question_id = "persisted-learning"
    assignments[0].post_question_id = "persisted-post"
    db.commit()

    reserved = get_active_pilot_reserved_question_ids(db, student_id=1)

    assert reserved[:3] == (
        "persisted-pre",
        "persisted-learning",
        "persisted-post",
    )
    assert reserved == tuple(
        question_id
        for assignment in assignments
        for question_id in (
            assignment.pre_question_id,
            assignment.learning_question_id,
            assignment.post_question_id,
        )
    )


@pytest.mark.parametrize("assignment_count", [0, 8, 10])
def test_incomplete_assignment_set_fails_closed(
    db: Session,
    assignment_count: int,
) -> None:
    add_enrollment(db, assignment_count=assignment_count)

    with pytest.raises(PilotReservedQuestionStateError):
        get_active_pilot_reserved_question_ids(db, student_id=1)


def test_resolver_does_not_commit_or_mutate_persisted_rows(db: Session) -> None:
    add_enrollment(db)
    before = list(
        db.scalars(select(PilotSkillAssignment).order_by(PilotSkillAssignment.id))
    )
    before_values = [
        (item.pre_question_id, item.learning_question_id, item.post_question_id)
        for item in before
    ]
    db.commit = pytest.fail  # type: ignore[method-assign]

    reserved = get_active_pilot_reserved_question_ids(db, student_id=1)

    assert reserved
    assert [
        (item.pre_question_id, item.learning_question_id, item.post_question_id)
        for item in before
    ] == before_values


def test_resolver_does_not_call_assignment_recomputation(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_enrollment(db)
    import app.services.pilot_assessment_assignment as assignment_service

    monkeypatch.setattr(
        assignment_service,
        "assign_pilot_items",
        lambda **_kwargs: pytest.fail("assignment recomputation was called"),
    )

    assert get_active_pilot_reserved_question_ids(db, student_id=1)

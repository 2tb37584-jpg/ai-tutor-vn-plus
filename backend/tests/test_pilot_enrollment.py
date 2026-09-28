from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.entities import (
    PilotEnrollment,
    PilotSkillAssignment,
    Student,
    TutorSession,
    User,
)
from app.services import pilot_enrollment
from app.services.pilot_assessment_assignment import PilotSkillAssignment as FrozenAssignment


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(email="synthetic@example.com", password_hash="hash")
        session.add(user)
        session.flush()
        session.add(Student(id=1, owner_id=user.id, display_name="Synthetic", grade=8))
        session.commit()
        yield session


def _assignments() -> tuple[FrozenAssignment, ...]:
    return (
        FrozenAssignment(
            skill_code="skill.one",
            pre_question_id="pre-1",
            learning_question_id="learning-1",
            post_question_id="post-1",
        ),
        FrozenAssignment(
            skill_code="skill.two",
            pre_question_id="pre-2",
            learning_question_id="learning-2",
            post_question_id="post-2",
        ),
    )


def _patch_creation(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seeds: list[str] = []
    monkeypatch.setattr(pilot_enrollment, "_generate_public_id", lambda: "public-opaque")
    monkeypatch.setattr(
        pilot_enrollment,
        "_generate_assignment_seed",
        lambda: seeds.append("seed-opaque") or "seed-opaque",
    )
    monkeypatch.setattr(
        pilot_enrollment,
        "assign_pilot_items",
        lambda *, assignment_seed: (
            seeds.append(assignment_seed) or _assignments()
        ),
    )
    return seeds


def test_creation_starts_pre_and_persists_all_assignment_state(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seeds = _patch_creation(monkeypatch)

    enrollment = pilot_enrollment.create_pilot_enrollment(db, student_id=1)

    assert enrollment.phase == "pre"
    rows = db.scalars(
        select(PilotSkillAssignment).order_by(PilotSkillAssignment.id)
    ).all()
    assert [
        (
            row.skill_code,
            row.pre_question_id,
            row.learning_question_id,
            row.post_question_id,
        )
        for row in rows
    ] == [
        ("skill.one", "pre-1", "learning-1", "post-1"),
        ("skill.two", "pre-2", "learning-2", "post-2"),
    ]
    assert seeds == ["seed-opaque", "seed-opaque"]
    assert all(
        row.pre_verification_status is None
        and row.pre_submitted_at is None
        and row.learning_completed_at is None
        and row.post_verification_status is None
        and row.post_submitted_at is None
        for row in rows
    )


def test_public_id_comes_from_server_generator(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_creation(monkeypatch)

    enrollment = pilot_enrollment.create_pilot_enrollment(db, student_id=1)

    assert enrollment.public_id == "public-opaque"
    assert enrollment.public_id != "1"
    assert len(enrollment.public_id) <= 64


def test_assignment_seed_forwarded_once_and_service_does_not_commit(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[str] = []
    monkeypatch.setattr(pilot_enrollment, "_generate_public_id", lambda: "public-id")
    monkeypatch.setattr(
        pilot_enrollment,
        "_generate_assignment_seed",
        lambda: "seed-id",
    )
    monkeypatch.setattr(
        pilot_enrollment,
        "assign_pilot_items",
        lambda *, assignment_seed: (
            received.append(assignment_seed) or _assignments()
        ),
    )

    enrollment = pilot_enrollment.create_pilot_enrollment(db, student_id=1)

    assert received == ["seed-id"]
    assert db.in_transaction()
    db.rollback()
    assert db.scalar(select(PilotEnrollment)) is None
    assert enrollment.id is not None


def test_models_do_not_persist_seed_or_raw_answer_fields() -> None:
    enrollment_columns = set(PilotEnrollment.__table__.columns.keys())
    assignment_columns = set(PilotSkillAssignment.__table__.columns.keys())

    assert "assignment_seed" not in enrollment_columns
    assert "assignment_seed" not in assignment_columns
    assert not any(
        name in assignment_columns
        for name in ("raw_answer", "answer", "expected_answer", "verification_reference")
    )


def test_role_ids_are_pairwise_distinct_and_db_rejects_duplicates(db: Session) -> None:
    enrollment = PilotEnrollment(public_id="public", student_id=1, phase="pre")
    db.add(enrollment)
    db.flush()
    db.add(
        PilotSkillAssignment(
            pilot_enrollment_id=enrollment.id,
            skill_code="skill",
            pre_question_id="same",
            learning_question_id="same",
            post_question_id="post",
        )
    )

    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_second_non_terminal_enrollment_is_rejected(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_creation(monkeypatch)
    pilot_enrollment.create_pilot_enrollment(db, student_id=1)

    with pytest.raises(ValueError, match="non-terminal"):
        pilot_enrollment.create_pilot_enrollment(db, student_id=1)


def test_new_enrollment_allowed_after_previous_is_complete(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = iter(("public-one", "public-two"))
    monkeypatch.setattr(pilot_enrollment, "_generate_public_id", lambda: next(calls))
    monkeypatch.setattr(
        pilot_enrollment,
        "_generate_assignment_seed",
        lambda: "seed",
    )
    monkeypatch.setattr(
        pilot_enrollment,
        "assign_pilot_items",
        lambda *, assignment_seed: _assignments(),
    )

    first = pilot_enrollment.create_pilot_enrollment(db, student_id=1)
    first.phase = "complete"
    db.commit()

    second = pilot_enrollment.create_pilot_enrollment(db, student_id=1)

    assert second.public_id == "public-two"
    assert second.phase == "pre"


def test_database_partial_unique_index_rejects_two_non_terminal_rows(db: Session) -> None:
    db.add_all(
        [
            PilotEnrollment(public_id="one", student_id=1, phase="pre"),
            PilotEnrollment(public_id="two", student_id=1, phase="intervention"),
        ]
    )

    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_tutor_session_provenance_is_nullable_fk() -> None:
    table = TutorSession.__table__
    column = table.c.pilot_skill_assignment_id

    assert column.nullable is True
    foreign_keys = list(column.foreign_keys)
    assert len(foreign_keys) == 1
    assert str(foreign_keys[0].target_fullname) == "pilot_skill_assignments.id"
    assert foreign_keys[0].ondelete == "SET NULL"


def test_assignment_status_vocabulary_is_enforced(db: Session) -> None:
    enrollment = PilotEnrollment(public_id="public-status", student_id=1, phase="pre")
    db.add(enrollment)
    db.flush()
    db.add(
        PilotSkillAssignment(
            pilot_enrollment_id=enrollment.id,
            skill_code="skill",
            pre_question_id="pre",
            learning_question_id="learning",
            post_question_id="post",
            pre_verification_status="not-a-status",
        )
    )

    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_enrollment_timestamps_are_naive_utc_datetimes(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_creation(monkeypatch)

    enrollment = pilot_enrollment.create_pilot_enrollment(db, student_id=1)

    assert isinstance(enrollment.created_at, datetime)
    assert isinstance(enrollment.updated_at, datetime)
    assert enrollment.created_at.tzinfo is None
    assert enrollment.updated_at.tzinfo is None


def test_generated_values_do_not_use_learner_pii(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pilot_enrollment, "_generate_public_id", lambda: "opaque-public")
    monkeypatch.setattr(
        pilot_enrollment,
        "_generate_assignment_seed",
        lambda: "opaque-seed",
    )
    monkeypatch.setattr(
        pilot_enrollment,
        "assign_pilot_items",
        lambda *, assignment_seed: _assignments(),
    )

    enrollment = pilot_enrollment.create_pilot_enrollment(db, student_id=1)

    assert "1" not in enrollment.public_id
    assert "synthetic@example.com" not in enrollment.public_id


def test_migration_revision_is_correct() -> None:
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0008_pilot_enrollment_state.py"
    )
    migration_text = migration_path.read_text(encoding="utf-8")

    assert 'revision: str = "0008_pilot_enrollment_state"' in migration_text
    assert 'down_revision: Union[str, Sequence[str], None] = "0007_tutor_authored_question_id"' in migration_text

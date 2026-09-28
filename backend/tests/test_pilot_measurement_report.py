from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from io import StringIO
import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.entities import (
    PilotEnrollment,
    PilotSkillAssignment,
    Student,
    User,
)
from app.services import pilot_measurement_report as report_module
from app.services.pilot_measurement import PilotAssessmentRecord
from app.services.pilot_measurement_projection import (
    PilotMeasurementProjectionStateError,
)


@pytest.fixture
def db_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions: list[Session] = []

    def make_session() -> Session:
        db = Session(engine, autoflush=False)
        sessions.append(db)
        return db

    yield make_session
    for db in sessions:
        db.close()
    engine.dispose()


def add_enrollment(
    db: Session,
    *,
    public_id: str,
    student_number: int,
    phase: str = "intervention",
    enrollment_id: int | None = None,
) -> tuple[PilotEnrollment, list[PilotSkillAssignment]]:
    user = User(
        email=f"synthetic-{student_number}@example.test",
        password_hash="synthetic",
    )
    db.add(user)
    db.flush()
    student = Student(
        owner_id=user.id,
        display_name=f"Synthetic {student_number}",
        grade=8,
    )
    db.add(student)
    db.flush()
    enrollment = PilotEnrollment(
        **({"id": enrollment_id} if enrollment_id is not None else {}),
        public_id=public_id,
        student_id=student.id,
        phase=phase,
    )
    db.add(enrollment)
    db.flush()
    assignments = [
        PilotSkillAssignment(
            pilot_enrollment_id=enrollment.id,
            skill_code=f"synthetic.skill.{student_number}.{index}",
            pre_question_id=f"synthetic.pre.{student_number}.{index}",
            learning_question_id=f"synthetic.learning.{student_number}.{index}",
            post_question_id=f"synthetic.post.{student_number}.{index}",
        )
        for index in range(9)
    ]
    db.add_all(assignments)
    db.flush()
    return enrollment, assignments


def set_phase(
    assignments: list[PilotSkillAssignment], *, phase: str, correct: int
) -> None:
    for index, assignment in enumerate(assignments):
        setattr(
            assignment,
            f"{phase}_verification_status",
            "correct" if index < correct else "incorrect",
        )
        setattr(
            assignment,
            f"{phase}_submitted_at",
            datetime(2026, 1, 1),
        )


def set_retryable(
    assignments: list[PilotSkillAssignment], *, phase: str, status: str
) -> None:
    setattr(assignments[0], f"{phase}_verification_status", status)


def test_empty_database_returns_m09_22_empty_aggregate(db_factory) -> None:
    report = report_module.build_aggregate_pilot_measurement_report(db_factory())

    assert report.matched_learner_count == 0
    assert report.mean_pre_score is None
    assert report.mean_post_score is None
    assert report.mean_paired_delta is None
    assert report.median_paired_delta is None
    assert report.improved_count == report.unchanged_count == report.declined_count == 0
    assert report.missing_pre == report.missing_post == 0
    assert report.invalid_incomplete == 0
    assert report.unsupported_verification == 0
    assert report.indeterminate_verification == 0


def test_enrollments_project_once_in_id_order_and_all_phases_are_included(
    db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = db_factory()
    add_enrollment(
        db,
        public_id="opaque-later",
        student_number=1,
        phase="complete",
        enrollment_id=30,
    )
    add_enrollment(
        db,
        public_id="opaque-earlier",
        student_number=2,
        phase="pre",
        enrollment_id=10,
    )
    db.commit()
    received: list[int] = []
    calculate_calls: list[tuple[PilotAssessmentRecord, ...]] = []

    def project(_db: Session, *, enrollment_id: int):
        received.append(enrollment_id)
        return ()

    expected = report_module.PilotAggregateMeasurementReport(
        0, None, None, None, None, 0, 0, 0, 0, 0, 0, 0, 0
    )

    def calculate(records):
        calculate_calls.append(tuple(records))
        return expected

    monkeypatch.setattr(report_module, "project_pilot_assessment_records", project)
    monkeypatch.setattr(report_module, "calculate_pilot_measurement", calculate)

    result = report_module.build_aggregate_pilot_measurement_report(db)

    assert result == expected
    assert received == [10, 30]
    assert len(calculate_calls) == 1
    assert calculate_calls == [()]


def test_valid_synthetic_cohort_uses_m09_22_aggregate_math(db_factory) -> None:
    db = db_factory()
    _, first = add_enrollment(db, public_id="opaque-a", student_number=1)
    set_phase(first, phase="pre", correct=6)
    set_phase(first, phase="post", correct=8)
    _, second = add_enrollment(db, public_id="opaque-b", student_number=2)
    set_phase(second, phase="pre", correct=7)
    set_phase(second, phase="post", correct=6)
    db.commit()

    report = report_module.build_aggregate_pilot_measurement_report(db)

    assert report.matched_learner_count == 2
    assert report.mean_pre_score == pytest.approx(13 / 18)
    assert report.mean_post_score == pytest.approx(7 / 9)
    assert report.mean_paired_delta == pytest.approx(1 / 18)
    assert report.median_paired_delta == pytest.approx(1 / 18)
    assert (
        report.improved_count,
        report.unchanged_count,
        report.declined_count,
    ) == (1, 0, 1)


def test_m09_22_missing_and_exclusion_counts_are_preserved(db_factory) -> None:
    db = db_factory()
    _, only_pre = add_enrollment(db, public_id="opaque-pre", student_number=1)
    set_phase(only_pre, phase="pre", correct=5)
    _, only_post = add_enrollment(db, public_id="opaque-post", student_number=2)
    set_phase(only_post, phase="post", correct=5)
    _, invalid = add_enrollment(db, public_id="opaque-invalid", student_number=3)
    invalid[0].pre_verification_status = "correct"  # no timestamp => invalid
    _, unsupported = add_enrollment(
        db, public_id="opaque-unsupported", student_number=4
    )
    set_retryable(unsupported, phase="pre", status="unsupported")
    _, indeterminate = add_enrollment(
        db, public_id="opaque-indeterminate", student_number=5
    )
    set_retryable(indeterminate, phase="post", status="indeterminate")
    db.commit()

    report = report_module.build_aggregate_pilot_measurement_report(db)

    assert report.matched_learner_count == 0
    assert report.missing_pre == 2
    assert report.missing_post == 3
    assert report.invalid_incomplete == 1
    assert report.unsupported_verification == 1
    assert report.indeterminate_verification == 1


def test_never_started_enrollment_does_not_become_missing_both_phases(
    db_factory,
) -> None:
    db = db_factory()
    add_enrollment(db, public_id="opaque-never-started", student_number=1)
    db.commit()

    report = report_module.build_aggregate_pilot_measurement_report(db)

    assert report.missing_pre == 0
    assert report.missing_post == 0
    assert report.matched_learner_count == 0


def test_projection_error_aborts_whole_report(
    db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = db_factory()
    add_enrollment(db, public_id="opaque-a", student_number=1)
    add_enrollment(db, public_id="opaque-b", student_number=2)
    db.commit()
    calls = 0

    def project(_db: Session, *, enrollment_id: int):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PilotMeasurementProjectionStateError("synthetic private failure")
        return ()

    monkeypatch.setattr(report_module, "project_pilot_assessment_records", project)
    with pytest.raises(PilotMeasurementProjectionStateError):
        report_module.build_aggregate_pilot_measurement_report(db)
    assert calls == 2


def test_aggregate_serialization_contains_no_learner_or_question_details(
    db_factory,
) -> None:
    db = db_factory()
    _enrollment, assignments = add_enrollment(
        db,
        public_id="SENTINEL_PUBLIC_ID",
        student_number=42,
    )
    set_phase(assignments, phase="pre", correct=6)
    set_phase(assignments, phase="post", correct=7)
    db.commit()

    report = report_module.build_aggregate_pilot_measurement_report(db)
    output = report_module.serialize_aggregate_report(report)

    assert set(report.__dataclass_fields__) == {
        "matched_learner_count",
        "mean_pre_score",
        "mean_post_score",
        "mean_paired_delta",
        "median_paired_delta",
        "improved_count",
        "unchanged_count",
        "declined_count",
        "missing_pre",
        "missing_post",
        "invalid_incomplete",
        "unsupported_verification",
        "indeterminate_verification",
    }
    assert "matched_learners" not in output
    for private_value in (
        "learner_id",
        "public_id",
        "student_id",
        "SENTINEL_PUBLIC_ID",
        "SENTINEL_PUBLIC_ID",
        "synthetic.pre.42.0",
        "synthetic.post.42.0",
        "synthetic.skill.42.0",
        "question_id",
    ):
        assert private_value not in output


def test_command_success_prints_one_deterministic_json_object(
    db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = db_factory()
    add_enrollment(db, public_id="opaque-command", student_number=1)
    db.commit()
    monkeypatch.setattr(report_module, "SessionLocal", lambda: db)
    outputs: list[str] = []

    for _ in range(2):
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            assert report_module.main() == 0
        outputs.append(stdout.getvalue())
        assert stderr.getvalue() == ""

    assert outputs[0] == outputs[1]
    assert outputs[0].count("\n") == 1
    assert outputs[0].startswith("{") and outputs[0].endswith("}\n")
    assert isinstance(json.loads(outputs[0]), dict)
    assert "opaque-command" not in outputs[0]


def test_command_projection_failure_is_generic_and_emits_no_stdout(
    db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = db_factory()
    add_enrollment(db, public_id="SENTINEL_PRIVATE_ENROLLMENT", student_number=1)
    db.commit()
    monkeypatch.setattr(report_module, "SessionLocal", lambda: db)
    def fail_projection(*_args, **_kwargs):
        raise PilotMeasurementProjectionStateError("SENTINEL_INTERNAL_DETAIL")

    monkeypatch.setattr(report_module, "project_pilot_assessment_records", fail_projection)
    stdout, stderr = StringIO(), StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        result = report_module.main()

    assert result == 1
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "Pilot measurement report unavailable\n"
    assert "SENTINEL_INTERNAL_DETAIL" not in stderr.getvalue()


def test_report_does_not_explicitly_flush_commit_rollback_or_mutate(
    db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = db_factory()
    enrollment, assignments = add_enrollment(
        db,
        public_id="opaque-read-only",
        student_number=1,
    )
    set_phase(assignments, phase="pre", correct=4)
    db.commit()
    before = [
        (
            item.pre_verification_status,
            item.pre_submitted_at,
            item.post_verification_status,
            item.post_submitted_at,
        )
        for item in assignments
    ]
    enrollment_id = enrollment.id
    monkeypatch.setattr(db, "flush", lambda *_a, **_k: pytest.fail("flush called"))
    monkeypatch.setattr(db, "commit", lambda *_a, **_k: pytest.fail("commit called"))
    monkeypatch.setattr(db, "rollback", lambda *_a, **_k: pytest.fail("rollback called"))

    report_module.build_aggregate_pilot_measurement_report(db)

    after = [
        (
            item.pre_verification_status,
            item.pre_submitted_at,
            item.post_verification_status,
            item.post_submitted_at,
        )
        for item in assignments
    ]
    assert after == before
    assert (
        db.scalar(select(PilotEnrollment.id).where(PilotEnrollment.id == enrollment_id))
        == enrollment_id
    )

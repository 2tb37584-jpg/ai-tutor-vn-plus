from datetime import datetime
from inspect import signature

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.entities import PilotEnrollment, PilotSkillAssignment, Student, User
from app.services.pilot_measurement import calculate_pilot_measurement
from app.services.pilot_measurement_projection import (
    PilotMeasurementProjectionNotFound,
    PilotMeasurementProjectionStateError,
    project_pilot_assessment_records,
)


@pytest.fixture
def db_and_enrollment() -> tuple[Session, PilotEnrollment]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = User(email="synthetic@example.com", password_hash="hash")
    db.add(user)
    db.flush()
    student = Student(owner_id=user.id, display_name="Synthetic", grade=8)
    db.add(student)
    db.flush()
    enrollment = PilotEnrollment(
        public_id="opaque-pilot-learner-a", student_id=student.id, phase="pre"
    )
    db.add(enrollment)
    db.flush()
    add_assignments(db, enrollment, count=9)
    db.commit()
    yield db, enrollment
    db.close()


def add_assignments(
    db: Session, enrollment: PilotEnrollment, *, count: int
) -> list[PilotSkillAssignment]:
    start_index = len(
        db.scalars(
            select(PilotSkillAssignment.id).where(
                PilotSkillAssignment.pilot_enrollment_id == enrollment.id
            )
        ).all()
    )
    assignments = [
        PilotSkillAssignment(
            pilot_enrollment_id=enrollment.id,
            skill_code=f"synthetic.skill.{start_index + index:02d}",
            pre_question_id=f"synthetic.pre.{start_index + index:02d}",
            learning_question_id=f"synthetic.learning.{start_index + index:02d}",
            post_question_id=f"synthetic.post.{start_index + index:02d}",
        )
        for index in range(count)
    ]
    db.add_all(assignments)
    db.flush()
    return assignments


def assignments_for(
    db: Session, enrollment: PilotEnrollment
) -> list[PilotSkillAssignment]:
    return list(
        db.scalars(
            select(PilotSkillAssignment)
            .where(PilotSkillAssignment.pilot_enrollment_id == enrollment.id)
            .order_by(PilotSkillAssignment.id)
        ).all()
    )


def set_phase(
    assignments: list[PilotSkillAssignment],
    phase: str,
    statuses: list[str | None],
) -> None:
    for assignment, status in zip(assignments, statuses, strict=True):
        setattr(assignment, f"{phase}_verification_status", status)
        setattr(
            assignment,
            f"{phase}_submitted_at",
            None if status in (None, "unsupported", "indeterminate") else datetime(2026, 1, 1),
        )


def item_statuses(*, correct: int, count: int = 9) -> list[str]:
    return ["correct"] * correct + ["incorrect"] * (count - correct)


def test_missing_enrollment_raises_not_found(
    db_and_enrollment: tuple[Session, PilotEnrollment],
) -> None:
    db, _ = db_and_enrollment
    with pytest.raises(PilotMeasurementProjectionNotFound):
        project_pilot_assessment_records(db, enrollment_id=99999)


@pytest.mark.parametrize("public_id", [None, "", "   ", []])
def test_empty_or_malformed_public_id_fails_closed(
    db_and_enrollment: tuple[Session, PilotEnrollment], public_id: object
) -> None:
    db, enrollment = db_and_enrollment
    enrollment.public_id = public_id  # type: ignore[assignment]
    with pytest.raises(PilotMeasurementProjectionStateError):
        project_pilot_assessment_records(db, enrollment_id=enrollment.id)


def test_pairing_uses_only_opaque_enrollment_public_id(
    db_and_enrollment: tuple[Session, PilotEnrollment],
) -> None:
    db, enrollment = db_and_enrollment
    assignments = assignments_for(db, enrollment)
    set_phase(assignments, "pre", item_statuses(correct=4))

    (record,) = project_pilot_assessment_records(db, enrollment_id=enrollment.id)

    assert record.learner_id == "opaque-pilot-learner-a"
    assert record.learner_id != str(enrollment.student_id)
    assert record.learner_id != str(enrollment.id)
    assert set(record.__dataclass_fields__) == {
        "learner_id",
        "phase",
        "outcome",
        "verified_correct_items",
        "valid_scored_items",
    }


def test_nine_scored_pre_items_project_valid_score_and_denominator(
    db_and_enrollment: tuple[Session, PilotEnrollment],
) -> None:
    db, enrollment = db_and_enrollment
    set_phase(assignments_for(db, enrollment), "pre", item_statuses(correct=6))

    (record,) = project_pilot_assessment_records(db, enrollment_id=enrollment.id)

    assert (record.phase, record.outcome) == ("pre", "valid")
    assert record.verified_correct_items == 6
    assert record.valid_scored_items == 9


def test_nine_scored_post_items_project_valid_score(
    db_and_enrollment: tuple[Session, PilotEnrollment],
) -> None:
    db, enrollment = db_and_enrollment
    set_phase(assignments_for(db, enrollment), "post", item_statuses(correct=8))

    (record,) = project_pilot_assessment_records(db, enrollment_id=enrollment.id)

    assert (record.phase, record.outcome) == ("post", "valid")
    assert (record.verified_correct_items, record.valid_scored_items) == (8, 9)


def test_both_valid_records_are_ordered_pre_then_post(
    db_and_enrollment: tuple[Session, PilotEnrollment],
) -> None:
    db, enrollment = db_and_enrollment
    assignments = assignments_for(db, enrollment)
    set_phase(assignments, "pre", item_statuses(correct=6))
    set_phase(assignments, "post", item_statuses(correct=8))

    records = project_pilot_assessment_records(db, enrollment_id=enrollment.id)

    assert [record.phase for record in records] == ["pre", "post"]


@pytest.mark.parametrize("phase", ["pre", "post"])
def test_untouched_phase_has_no_record(
    db_and_enrollment: tuple[Session, PilotEnrollment], phase: str
) -> None:
    db, enrollment = db_and_enrollment
    other = "post" if phase == "pre" else "pre"
    set_phase(assignments_for(db, enrollment), other, item_statuses(correct=5))

    records = project_pilot_assessment_records(db, enrollment_id=enrollment.id)

    assert [record.phase for record in records] == [other]


def test_no_pre_or_post_state_projects_empty_tuple(
    db_and_enrollment: tuple[Session, PilotEnrollment],
) -> None:
    db, enrollment = db_and_enrollment
    assert project_pilot_assessment_records(db, enrollment_id=enrollment.id) == ()


@pytest.mark.parametrize("phase", ["pre", "post"])
def test_single_valid_phase_projects_one_record(
    db_and_enrollment: tuple[Session, PilotEnrollment], phase: str
) -> None:
    db, enrollment = db_and_enrollment
    set_phase(assignments_for(db, enrollment), phase, item_statuses(correct=7))

    records = project_pilot_assessment_records(db, enrollment_id=enrollment.id)

    assert len(records) == 1
    assert records[0].phase == phase
    assert records[0].outcome == "valid"


def test_scored_prefix_with_untouched_remainder_is_invalid(
    db_and_enrollment: tuple[Session, PilotEnrollment],
) -> None:
    db, enrollment = db_and_enrollment
    assignments = assignments_for(db, enrollment)
    assignments[0].pre_verification_status = "correct"
    assignments[0].pre_submitted_at = datetime(2026, 1, 1)

    (record,) = project_pilot_assessment_records(db, enrollment_id=enrollment.id)

    assert record.outcome == "invalid_incomplete"
    assert (record.verified_correct_items, record.valid_scored_items) == (0, 0)


@pytest.mark.parametrize(
    ("retry_status", "expected_outcome"),
    [
        ("unsupported", "unsupported_verification"),
        ("indeterminate", "indeterminate_verification"),
    ],
)
def test_retryable_status_after_scored_prefix_projects_exclusion_with_zero_counts(
    db_and_enrollment: tuple[Session, PilotEnrollment],
    retry_status: str,
    expected_outcome: str,
) -> None:
    db, enrollment = db_and_enrollment
    assignments = assignments_for(db, enrollment)
    statuses: list[str | None] = ["correct", "incorrect", retry_status] + [None] * 6
    set_phase(assignments, "pre", statuses)

    (record,) = project_pilot_assessment_records(db, enrollment_id=enrollment.id)

    assert record.outcome == expected_outcome
    assert (record.verified_correct_items, record.valid_scored_items) == (0, 0)


@pytest.mark.parametrize(
    ("retry_status", "later_status"),
    [("unsupported", "correct"), ("indeterminate", "incorrect")],
)
def test_retryable_item_followed_by_touched_item_is_invalid(
    db_and_enrollment: tuple[Session, PilotEnrollment],
    retry_status: str,
    later_status: str,
) -> None:
    db, enrollment = db_and_enrollment
    assignments = assignments_for(db, enrollment)
    statuses: list[str | None] = [retry_status, later_status] + [None] * 7
    set_phase(assignments, "pre", statuses)

    (record,) = project_pilot_assessment_records(db, enrollment_id=enrollment.id)

    assert record.outcome == "invalid_incomplete"


def test_scored_item_after_untouched_gap_is_invalid(
    db_and_enrollment: tuple[Session, PilotEnrollment],
) -> None:
    db, enrollment = db_and_enrollment
    assignments = assignments_for(db, enrollment)
    statuses: list[str | None] = [None, "correct"] + [None] * 7
    set_phase(assignments, "pre", statuses)

    (record,) = project_pilot_assessment_records(db, enrollment_id=enrollment.id)

    assert record.outcome == "invalid_incomplete"


@pytest.mark.parametrize(
    ("status", "submitted"),
    [
        ("correct", None),
        ("incorrect", None),
        ("unsupported", datetime(2026, 1, 1)),
        ("indeterminate", datetime(2026, 1, 1)),
        (None, datetime(2026, 1, 1)),
        ("unknown", None),
        (["correct"], None),
    ],
)
def test_malformed_persisted_status_timestamp_pair_is_invalid(
    db_and_enrollment: tuple[Session, PilotEnrollment],
    status: object,
    submitted: datetime | None,
) -> None:
    db, enrollment = db_and_enrollment
    assignment = assignments_for(db, enrollment)[0]
    assignment.pre_verification_status = status  # type: ignore[assignment]
    assignment.pre_submitted_at = submitted

    (record,) = project_pilot_assessment_records(db, enrollment_id=enrollment.id)

    assert record.outcome == "invalid_incomplete"
    assert (record.verified_correct_items, record.valid_scored_items) == (0, 0)


@pytest.mark.parametrize("count", [8, 10])
def test_assignment_count_other_than_nine_projects_both_phases_invalid(
    db_and_enrollment: tuple[Session, PilotEnrollment], count: int
) -> None:
    db, enrollment = db_and_enrollment
    assignments = assignments_for(db, enrollment)
    if count == 8:
        db.delete(assignments[-1])
        db.flush()
    else:
        add_assignments(db, enrollment, count=1)

    records = project_pilot_assessment_records(db, enrollment_id=enrollment.id)

    assert [(record.phase, record.outcome) for record in records] == [
        ("pre", "invalid_incomplete"),
        ("post", "invalid_incomplete"),
    ]
    assert all(
        (record.verified_correct_items, record.valid_scored_items) == (0, 0)
        for record in records
    )


def test_projection_does_not_flush_commit_rollback_or_mutate(
    db_and_enrollment: tuple[Session, PilotEnrollment],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, enrollment = db_and_enrollment
    assignments = assignments_for(db, enrollment)
    assignments[0].pre_verification_status = "unsupported"
    before = [
        (
            assignment.pre_verification_status,
            assignment.pre_submitted_at,
            assignment.post_verification_status,
            assignment.post_submitted_at,
        )
        for assignment in assignments
    ]
    monkeypatch.setattr(db, "flush", lambda *_a, **_k: pytest.fail("flush called"))
    monkeypatch.setattr(db, "commit", lambda *_a, **_k: pytest.fail("commit called"))
    monkeypatch.setattr(db, "rollback", lambda *_a, **_k: pytest.fail("rollback called"))

    project_pilot_assessment_records(db, enrollment_id=enrollment.id)

    after = [
        (
            assignment.pre_verification_status,
            assignment.pre_submitted_at,
            assignment.post_verification_status,
            assignment.post_submitted_at,
        )
        for assignment in assignments
    ]
    assert after == before


def test_projection_api_has_no_seed_or_raw_answer_inputs() -> None:
    assert list(signature(project_pilot_assessment_records).parameters) == [
        "db",
        "enrollment_id",
    ]


def test_projected_valid_pair_is_accepted_by_m09_22_calculator(
    db_and_enrollment: tuple[Session, PilotEnrollment],
) -> None:
    db, enrollment = db_and_enrollment
    assignments = assignments_for(db, enrollment)
    set_phase(assignments, "pre", item_statuses(correct=6))
    set_phase(assignments, "post", item_statuses(correct=8))

    report = calculate_pilot_measurement(
        project_pilot_assessment_records(db, enrollment_id=enrollment.id)
    )

    assert report.matched_learner_count == 1
    assert report.matched_learners[0].pre_score == pytest.approx(6 / 9)
    assert report.matched_learners[0].post_score == pytest.approx(8 / 9)
    assert report.matched_learners[0].paired_delta == pytest.approx(2 / 9)


def test_projected_pre_only_record_counts_missing_post_in_m09_22(
    db_and_enrollment: tuple[Session, PilotEnrollment],
) -> None:
    db, enrollment = db_and_enrollment
    set_phase(assignments_for(db, enrollment), "pre", item_statuses(correct=6))

    report = calculate_pilot_measurement(
        project_pilot_assessment_records(db, enrollment_id=enrollment.id)
    )

    assert report.matched_learner_count == 0
    assert report.missing_post == 1


def test_projected_post_only_record_counts_missing_pre_in_m09_22(
    db_and_enrollment: tuple[Session, PilotEnrollment],
) -> None:
    db, enrollment = db_and_enrollment
    set_phase(assignments_for(db, enrollment), "post", item_statuses(correct=6))

    report = calculate_pilot_measurement(
        project_pilot_assessment_records(db, enrollment_id=enrollment.id)
    )

    assert report.matched_learner_count == 0
    assert report.missing_pre == 1


@pytest.mark.parametrize(
    ("phase", "outcome", "expected_counter"),
    [
        ("pre", "unsupported_verification", "unsupported_verification"),
        ("post", "indeterminate_verification", "indeterminate_verification"),
        ("pre", "invalid_incomplete", "invalid_incomplete"),
    ],
)
def test_projected_exclusions_count_in_m09_22_not_matched_denominator(
    db_and_enrollment: tuple[Session, PilotEnrollment],
    phase: str,
    outcome: str,
    expected_counter: str,
) -> None:
    db, enrollment = db_and_enrollment
    assignments = assignments_for(db, enrollment)
    if outcome == "unsupported_verification":
        set_phase(assignments, phase, ["unsupported"] + [None] * 8)
    elif outcome == "indeterminate_verification":
        set_phase(assignments, phase, ["indeterminate"] + [None] * 8)
    else:
        assignments[0].pre_verification_status = "correct"
        assignments[0].pre_submitted_at = None

    report = calculate_pilot_measurement(
        project_pilot_assessment_records(db, enrollment_id=enrollment.id)
    )

    assert report.matched_learner_count == 0
    assert getattr(report, expected_counter) == 1

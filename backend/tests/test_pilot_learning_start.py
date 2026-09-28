from dataclasses import replace
from datetime import datetime
import inspect

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.entities import PilotEnrollment, PilotSkillAssignment
from app.services import pilot_learning_start
from app.services.question_bank import get_question


_NOW = datetime(2026, 1, 1)
_ASSIGNMENTS = (
    (
        "arithmetic.signed_number_operations",
        "g8alg.signed-number-operations.001",
        "g8alg.signed-number-operations.002",
        "g8alg.signed-number-operations.003",
    ),
    (
        "algebra.expression.distributive_property",
        "g8alg.distributive-property.001",
        "g8alg.distributive-property.002",
        "g8alg.distributive-property.003",
    ),
    (
        "algebra.expression.combine_like_terms",
        "g8alg.combine-like-terms.001",
        "g8alg.combine-like-terms.002",
        "g8alg.combine-like-terms.003",
    ),
    (
        "algebra.expression.simplify",
        "g8alg.expression-simplify.001",
        "g8alg.expression-simplify.002",
        "g8alg.expression-simplify.003",
    ),
    (
        "algebra.identity.basic",
        "g8alg.identity-basic.001",
        "g8alg.identity-basic.002",
        "g8alg.identity-basic.003",
    ),
    (
        "algebra.linear_equation",
        "g8alg.linear-equation.001",
        "g8alg.linear-equation.002",
        "g8alg.linear-equation.003",
    ),
    (
        "algebra.equation.equivalent_transform",
        "g8alg.equivalent-transform.001",
        "g8alg.equivalent-transform.002",
        "g8alg.equivalent-transform.003",
    ),
    (
        "algebra.factorization",
        "g8alg.factorization.001",
        "g8alg.factorization.002",
        "g8alg.factorization.003",
    ),
    (
        "algebra.rational_expression.domain",
        "g8alg.rational-expression-domain.001",
        "g8alg.rational-expression-domain.002",
        "g8alg.rational-expression-domain.003",
    ),
)


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _add_enrollment(
    db: Session,
    *,
    phase: str = "intervention",
    assignment_count: int = 9,
    completed_prefix: int = 0,
) -> tuple[PilotEnrollment, list[PilotSkillAssignment]]:
    enrollment = PilotEnrollment(
        public_id=f"pilot-{phase}-{id(db)}",
        student_id=1,
        phase=phase,
    )
    db.add(enrollment)
    db.flush()

    rows: list[PilotSkillAssignment] = []
    specs = list(_ASSIGNMENTS)
    if assignment_count > len(specs):
        specs.append(("synthetic.extra", "extra.pre", "extra.learning", "extra.post"))
    for index, (skill, pre_id, learning_id, post_id) in enumerate(
        specs[:assignment_count]
    ):
        row = PilotSkillAssignment(
            pilot_enrollment_id=enrollment.id,
            skill_code=skill,
            pre_question_id=pre_id,
            learning_question_id=learning_id,
            post_question_id=post_id,
            pre_verification_status="correct" if index % 2 == 0 else "incorrect",
            pre_submitted_at=_NOW,
            learning_completed_at=_NOW if index < completed_prefix else None,
        )
        db.add(row)
        rows.append(row)
    db.commit()
    return enrollment, rows


def assignment_snapshot(
    assignments: list[PilotSkillAssignment],
) -> list[tuple[object, ...]]:
    return [
        (
            row.id,
            row.pilot_enrollment_id,
            row.skill_code,
            row.pre_question_id,
            row.learning_question_id,
            row.post_question_id,
            row.pre_verification_status,
            row.pre_submitted_at,
            row.learning_completed_at,
            row.post_verification_status,
            row.post_submitted_at,
        )
        for row in assignments
    ]


@pytest.mark.parametrize("completed_only", [False, True])
def test_missing_active_enrollment_is_not_found(
    db: Session,
    completed_only: bool,
) -> None:
    if completed_only:
        db.add(PilotEnrollment(public_id="completed", student_id=1, phase="complete"))
        db.commit()

    with pytest.raises(pilot_learning_start.PilotLearningStartNotFound):
        pilot_learning_start.get_next_pilot_learning_start(db, student_id=1)


@pytest.mark.parametrize("phase", ["pre", "post"])
def test_non_intervention_phase_is_unavailable(db: Session, phase: str) -> None:
    _add_enrollment(db, phase=phase)

    with pytest.raises(pilot_learning_start.PilotLearningStartUnavailable):
        pilot_learning_start.get_next_pilot_learning_start(db, student_id=1)


def test_valid_intervention_returns_exact_first_persisted_assignment(
    db: Session,
) -> None:
    _, assignments = _add_enrollment(db)

    result = pilot_learning_start.get_next_pilot_learning_start(db, student_id=1)

    assert result.pilot_skill_assignment_id == assignments[0].id
    assert result.item.id == assignments[0].learning_question_id
    assert result.item.skill_code == assignments[0].skill_code


def test_completed_prefix_selects_next_assignment_in_persisted_id_order(
    db: Session,
) -> None:
    _, assignments = _add_enrollment(db, completed_prefix=4)

    result = pilot_learning_start.get_next_pilot_learning_start(db, student_id=1)

    assert [row.id for row in assignments] == sorted(row.id for row in assignments)
    assert result.pilot_skill_assignment_id == assignments[4].id
    assert result.item.id == assignments[4].learning_question_id


@pytest.mark.parametrize("failure", ["missing", "skill-mismatch"])
def test_untrusted_learning_question_configuration_fails_closed(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    _, assignments = _add_enrollment(db)
    if failure == "missing":
        assignments[0].learning_question_id = "missing.learning.question"
        db.commit()
    else:
        item = get_question(assignments[0].learning_question_id)
        assert item is not None
        monkeypatch.setattr(
            pilot_learning_start,
            "get_question",
            lambda _question_id: replace(item, skill_code="algebra.factorization"),
        )

    with pytest.raises(pilot_learning_start.PilotLearningStartConfigurationError):
        pilot_learning_start.get_next_pilot_learning_start(db, student_id=1)


@pytest.mark.parametrize("assignment_count", [0, 8, 10])
def test_assignment_count_must_be_exactly_nine(
    db: Session,
    assignment_count: int,
) -> None:
    _add_enrollment(db, assignment_count=assignment_count)

    with pytest.raises(pilot_learning_start.PilotLearningStartStateError):
        pilot_learning_start.get_next_pilot_learning_start(db, student_id=1)


@pytest.mark.parametrize(
    ("status", "submitted_at"),
    [
        (None, None),
        ("correct", None),
        ("unsupported", None),
        ("indeterminate", None),
    ],
)
def test_incomplete_or_retryable_pre_state_fails_closed(
    db: Session,
    status: str | None,
    submitted_at: datetime | None,
) -> None:
    _, assignments = _add_enrollment(db)
    assignments[3].pre_verification_status = status
    assignments[3].pre_submitted_at = submitted_at
    db.commit()

    with pytest.raises(pilot_learning_start.PilotLearningStartStateError):
        pilot_learning_start.get_next_pilot_learning_start(db, student_id=1)


@pytest.mark.parametrize("post_field", ["post_verification_status", "post_submitted_at"])
def test_post_state_during_intervention_fails_closed(
    db: Session,
    post_field: str,
) -> None:
    _, assignments = _add_enrollment(db)
    setattr(
        assignments[2],
        post_field,
        "unsupported" if post_field.endswith("status") else _NOW,
    )
    db.commit()

    with pytest.raises(pilot_learning_start.PilotLearningStartStateError):
        pilot_learning_start.get_next_pilot_learning_start(db, student_id=1)


def test_non_prefix_learning_completion_fails_closed(db: Session) -> None:
    _, assignments = _add_enrollment(db, completed_prefix=2)
    assignments[4].learning_completed_at = _NOW
    db.commit()

    with pytest.raises(pilot_learning_start.PilotLearningStartStateError):
        pilot_learning_start.get_next_pilot_learning_start(db, student_id=1)


def test_all_learning_complete_while_intervention_fails_closed(db: Session) -> None:
    _add_enrollment(db, completed_prefix=9)

    with pytest.raises(pilot_learning_start.PilotLearningStartStateError):
        pilot_learning_start.get_next_pilot_learning_start(db, student_id=1)


def test_selection_does_not_flush_commit_or_mutate(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enrollment, assignments = _add_enrollment(db, completed_prefix=2)
    before_phase = enrollment.phase
    before_assignments = assignment_snapshot(assignments)
    monkeypatch.setattr(db, "flush", lambda: pytest.fail("selection must not flush"))
    monkeypatch.setattr(db, "commit", lambda: pytest.fail("selection must not commit"))

    pilot_learning_start.get_next_pilot_learning_start(db, student_id=1)

    assert enrollment.phase == before_phase
    assert assignment_snapshot(assignments) == before_assignments


def test_selection_has_no_assignment_seed_or_recomputation_dependency() -> None:
    source = inspect.getsource(pilot_learning_start)

    assert "assignment_seed" not in source
    assert "assign_pilot_items" not in source
    assert not hasattr(pilot_learning_start, "assign_pilot_items")
    assert not hasattr(pilot_learning_start, "PilotAssessmentAssignment")


def test_assignments_are_read_back_in_persisted_id_order(db: Session) -> None:
    enrollment, assignments = _add_enrollment(db, completed_prefix=1)

    persisted = db.scalars(
        select(PilotSkillAssignment)
        .where(PilotSkillAssignment.pilot_enrollment_id == enrollment.id)
        .order_by(PilotSkillAssignment.id)
    ).all()
    result = pilot_learning_start.get_next_pilot_learning_start(db, student_id=1)

    assert persisted == assignments
    assert result.pilot_skill_assignment_id == persisted[1].id

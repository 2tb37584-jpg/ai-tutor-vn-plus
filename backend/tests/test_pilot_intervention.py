from datetime import datetime
import inspect

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.entities import PilotEnrollment, PilotSkillAssignment, TutorSession
from app.services import pilot_intervention
from app.services.question_bank import QuestionBankItem


_NOW = datetime(2026, 4, 5, 6, 7, 8)
_SPECS = (
    ("arithmetic.signed_number_operations", "g8alg.signed-number-operations.001", "g8alg.signed-number-operations.002", "g8alg.signed-number-operations.003"),
    ("algebra.expression.distributive_property", "g8alg.distributive-property.001", "g8alg.distributive-property.002", "g8alg.distributive-property.003"),
    ("algebra.expression.combine_like_terms", "g8alg.combine-like-terms.001", "g8alg.combine-like-terms.002", "g8alg.combine-like-terms.003"),
    ("algebra.expression.simplify", "g8alg.expression-simplify.001", "g8alg.expression-simplify.002", "g8alg.expression-simplify.003"),
    ("algebra.identity.basic", "g8alg.identity-basic.001", "g8alg.identity-basic.002", "g8alg.identity-basic.003"),
    ("algebra.linear_equation", "g8alg.linear-equation.001", "g8alg.linear-equation.002", "g8alg.linear-equation.003"),
    ("algebra.equation.equivalent_transform", "g8alg.equivalent-transform.001", "g8alg.equivalent-transform.002", "g8alg.equivalent-transform.003"),
    ("algebra.factorization", "g8alg.factorization.001", "g8alg.factorization.002", "g8alg.factorization.003"),
    ("algebra.rational_expression.domain", "g8alg.rational-expression-domain.001", "g8alg.rational-expression-domain.002", "g8alg.rational-expression-domain.003"),
)


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _pilot(
    db: Session,
    *,
    phase: str = "intervention",
    completed_prefix: int = 0,
    assignment_count: int = 9,
    session_index: int = 0,
) -> tuple[PilotEnrollment, list[PilotSkillAssignment], TutorSession]:
    enrollment = PilotEnrollment(
        public_id=f"pilot-{id(db)}",
        student_id=1,
        phase=phase,
    )
    db.add(enrollment)
    db.flush()
    specs = list(_SPECS)
    if assignment_count > len(specs):
        specs.append(("synthetic.extra", "extra.pre", "extra.learning", "extra.post"))
    rows = [
        PilotSkillAssignment(
            pilot_enrollment_id=enrollment.id,
            skill_code=skill,
            pre_question_id=pre_id,
            learning_question_id=learning_id,
            post_question_id=post_id,
            pre_verification_status="correct" if index % 2 == 0 else "incorrect",
            pre_submitted_at=_NOW,
            learning_completed_at=_NOW if index < completed_prefix else None,
        )
        for index, (skill, pre_id, learning_id, post_id) in enumerate(
            specs[:assignment_count]
        )
    ]
    db.add_all(rows)
    db.flush()
    assigned = rows[session_index]
    session = TutorSession(
        student_id=1,
        current_state="transfer",
        primary_skill=assigned.skill_code,
        authored_question_id=assigned.learning_question_id,
        transfer_question_id=assigned.learning_question_id,
        pilot_skill_assignment_id=assigned.id,
        internal_expected_answer="unused by transfer verifier",
    )
    db.add(session)
    db.commit()
    return enrollment, rows, session


def test_exact_provenance_resolves_context_and_only_pre_post_exclusions(db: Session) -> None:
    _, rows, session = _pilot(db)

    context = pilot_intervention.resolve_pilot_intervention_context(db, session)

    assert context.pilot_skill_assignment_id == rows[0].id
    assert context.transfer_excluded_question_ids == (
        rows[0].pre_question_id,
        rows[0].post_question_id,
    )
    assert rows[0].learning_question_id not in context.transfer_excluded_question_ids
    assert context.transfer_item is not None
    assert context.transfer_item.id == rows[0].learning_question_id


def test_fourth_same_skill_transfer_item_is_valid(db: Session) -> None:
    _, rows, session = _pilot(db)
    session.transfer_question_id = "g8alg.signed-number-operations.004"
    rows[0].skill_code = "arithmetic.signed_number_operations"

    context = pilot_intervention.resolve_pilot_intervention_context(db, session)

    assert context.transfer_item is not None
    assert context.transfer_item.id == session.transfer_question_id


@pytest.mark.parametrize("role", ["pre_question_id", "post_question_id"])
def test_assessment_reserved_transfer_item_is_rejected(db: Session, role: str) -> None:
    _, rows, session = _pilot(db)
    session.transfer_question_id = getattr(rows[0], role)

    with pytest.raises(pilot_intervention.PilotInterventionStateError):
        pilot_intervention.resolve_pilot_intervention_context(db, session)


@pytest.mark.parametrize(
    ("transfer_question_id", "error_type"),
    [
        (None, pilot_intervention.PilotInterventionStateError),
        ("missing.authored.item", pilot_intervention.PilotInterventionConfigurationError),
        ("g8alg.linear-equation.001", pilot_intervention.PilotInterventionStateError),
    ],
)
def test_missing_or_wrong_skill_transfer_item_is_rejected(
    db: Session,
    transfer_question_id: str | None,
    error_type: type[Exception],
) -> None:
    _, _, session = _pilot(db)
    session.transfer_question_id = transfer_question_id

    with pytest.raises(error_type):
        pilot_intervention.resolve_pilot_intervention_context(db, session)


def test_post_phase_rejects_stale_intervention_session(db: Session) -> None:
    enrollment, rows, session = _pilot(
        db,
        phase="post",
        completed_prefix=9,
        session_index=8,
    )

    with pytest.raises(pilot_intervention.PilotInterventionStateError):
        pilot_intervention.resolve_pilot_intervention_context(db, session)

    assert all(row.learning_completed_at is not None for row in rows)
    assert enrollment.phase == "post"


@pytest.mark.parametrize(
    "mutation",
    [
        "assignment_missing",
        "enrollment_missing",
        "enrollment_student_mismatch",
        "student_mismatch",
        "authored_question_mismatch",
        "skill_mismatch",
        "non_intervention_phase",
    ],
)
def test_invalid_session_or_enrollment_provenance_fails_closed(
    db: Session,
    mutation: str,
) -> None:
    enrollment, rows, session = _pilot(db)
    if mutation == "assignment_missing":
        session.pilot_skill_assignment_id = 999
    elif mutation == "enrollment_missing":
        rows[0].pilot_enrollment_id = 999
    elif mutation == "enrollment_student_mismatch":
        enrollment.student_id = 2
    elif mutation == "student_mismatch":
        session.student_id = 2
    elif mutation == "authored_question_mismatch":
        session.authored_question_id = rows[1].learning_question_id
    elif mutation == "skill_mismatch":
        session.primary_skill = rows[1].skill_code
    else:
        enrollment.phase = "post"

    with pytest.raises(pilot_intervention.PilotInterventionStateError):
        pilot_intervention.resolve_pilot_intervention_context(db, session)


@pytest.mark.parametrize("assignment_count", [8, 10])
def test_assignment_count_must_be_exactly_nine(db: Session, assignment_count: int) -> None:
    _, _, session = _pilot(db, assignment_count=assignment_count)

    with pytest.raises(pilot_intervention.PilotInterventionStateError):
        pilot_intervention.resolve_pilot_intervention_context(db, session)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pre_verification_status", "unsupported"),
        ("pre_submitted_at", None),
        ("post_verification_status", "correct"),
        ("post_submitted_at", _NOW),
    ],
)
def test_unscored_pre_or_touched_post_fails_closed(
    db: Session,
    field: str,
    value: object,
) -> None:
    _, rows, session = _pilot(db)
    setattr(rows[0], field, value)

    with pytest.raises(pilot_intervention.PilotInterventionStateError):
        pilot_intervention.resolve_pilot_intervention_context(db, session)


def test_non_prefix_completion_fails_closed(db: Session) -> None:
    _, rows, session = _pilot(db)
    rows[1].learning_completed_at = _NOW

    with pytest.raises(pilot_intervention.PilotInterventionStateError):
        pilot_intervention.resolve_pilot_intervention_context(db, session)


def test_incomplete_session_assignment_must_be_first_incomplete(db: Session) -> None:
    _, _, session = _pilot(db, session_index=1)

    with pytest.raises(pilot_intervention.PilotInterventionStateError):
        pilot_intervention.resolve_pilot_intervention_context(db, session)


def test_completion_sets_exact_timestamp_and_only_selected_assignment(db: Session) -> None:
    _, rows, session = _pilot(db)
    before = [row.learning_completed_at for row in rows]

    result = pilot_intervention.complete_pilot_learning_assignment(
        db,
        session,
        received_at=_NOW,
    )

    assert result.assignment_completed_now is True
    assert rows[0].learning_completed_at == _NOW
    assert [row.learning_completed_at for row in rows[1:]] == before[1:]
    assert result.next_item is not None
    assert result.next_item.id == rows[1].learning_question_id
    assert result.next_item.skill_code == rows[1].skill_code
    assert result.enrollment_phase == "intervention"


def test_duplicate_completion_preserves_timestamp_and_returns_current_next_item(
    db: Session,
) -> None:
    first_time = datetime(2026, 1, 2)
    _, rows, session = _pilot(db, completed_prefix=1)
    rows[0].learning_completed_at = first_time
    session.pilot_skill_assignment_id = rows[0].id
    session.authored_question_id = rows[0].learning_question_id
    session.primary_skill = rows[0].skill_code

    result = pilot_intervention.complete_pilot_learning_assignment(
        db,
        session,
        received_at=_NOW,
    )

    assert result.assignment_completed_now is False
    assert rows[0].learning_completed_at == first_time
    assert rows[1].learning_completed_at is None
    assert result.next_item is not None
    assert result.next_item.id == rows[1].learning_question_id


@pytest.mark.parametrize("question_result", [None, "wrong_skill"])
def test_missing_or_mismatched_next_question_fails_closed_before_mutation(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    question_result: str | None,
) -> None:
    _, rows, session = _pilot(db)
    if question_result == "wrong_skill":
        monkeypatch.setattr(
            pilot_intervention,
            "get_question",
            lambda question_id: QuestionBankItem(
                id=question_id,
                skill_code="incorrect.skill",
                problem_text="synthetic",
                verification_reference="trusted",
                expected_answer="hidden",
                verification_family="numeric",
                difficulty=1,
            ),
        )
    else:
        monkeypatch.setattr(pilot_intervention, "get_question", lambda _question_id: None)

    with pytest.raises(pilot_intervention.PilotInterventionConfigurationError):
        pilot_intervention.complete_pilot_learning_assignment(
            db,
            session,
            received_at=_NOW,
        )
    assert rows[0].learning_completed_at is None


def test_ninth_completion_moves_only_enrollment_to_post(db: Session) -> None:
    enrollment, rows, session = _pilot(db, completed_prefix=8, session_index=8)

    result = pilot_intervention.complete_pilot_learning_assignment(
        db,
        session,
        received_at=_NOW,
    )

    assert rows[8].learning_completed_at == _NOW
    assert all(row.learning_completed_at is not None for row in rows)
    assert enrollment.phase == "post"
    assert result.enrollment_phase == "post"
    assert result.next_item is None
    assert result.assignment_completed_now is True


def test_service_does_not_commit_or_accept_assignment_seed(db: Session, monkeypatch) -> None:
    _, _, session = _pilot(db)
    monkeypatch.setattr(db, "commit", lambda: pytest.fail("service must not commit"))

    result = pilot_intervention.complete_pilot_learning_assignment(
        db,
        session,
        received_at=_NOW,
    )

    assert result.next_item is not None
    assert "assignment_seed" not in inspect.signature(
        pilot_intervention.complete_pilot_learning_assignment
    ).parameters

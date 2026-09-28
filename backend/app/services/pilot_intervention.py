"""Trusted completion and exact progression for pilot intervention assignments."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import PilotEnrollment, PilotSkillAssignment, TutorSession
from app.services.question_bank import QuestionBankItem, get_question


_EXPECTED_ASSIGNMENT_COUNT = 9
_SCORED_PRE_STATUSES = {"correct", "incorrect"}


class PilotInterventionError(RuntimeError):
    """Base error for trusted pilot intervention processing."""


class PilotInterventionStateError(PilotInterventionError):
    """Persisted pilot provenance or intervention state is inconsistent."""


class PilotInterventionConfigurationError(PilotInterventionError):
    """A persisted trusted authored learning item cannot be resolved."""


@dataclass(frozen=True)
class PilotInterventionContext:
    pilot_skill_assignment_id: int
    transfer_excluded_question_ids: tuple[str, ...]


@dataclass(frozen=True)
class PilotInterventionProgression:
    next_item: QuestionBankItem | None
    enrollment_phase: str
    assignment_completed_now: bool


def resolve_pilot_intervention_context(
    db: Session,
    session: TutorSession,
) -> PilotInterventionContext:
    """Validate session provenance and return its PRE/POST transfer exclusions."""

    assignment_id = session.pilot_skill_assignment_id
    if assignment_id is None:
        raise PilotInterventionStateError("pilot assignment provenance is missing")

    with db.no_autoflush:
        assignment = db.get(PilotSkillAssignment, assignment_id)
        if assignment is None:
            raise PilotInterventionStateError("pilot assignment provenance is missing")
        enrollment = db.get(PilotEnrollment, assignment.pilot_enrollment_id)
        if enrollment is None:
            raise PilotInterventionStateError("pilot enrollment provenance is missing")
        assignments = db.scalars(
            select(PilotSkillAssignment)
            .where(PilotSkillAssignment.pilot_enrollment_id == enrollment.id)
            .order_by(PilotSkillAssignment.id)
        ).all()

    if assignment.pilot_enrollment_id != enrollment.id:
        raise PilotInterventionStateError("pilot assignment enrollment mismatch")
    if enrollment.student_id != session.student_id:
        raise PilotInterventionStateError("pilot session student mismatch")
    if enrollment.phase != "intervention":
        raise PilotInterventionStateError("pilot enrollment is not in intervention")
    if session.authored_question_id != assignment.learning_question_id:
        raise PilotInterventionStateError("pilot session question provenance mismatch")
    if session.primary_skill != assignment.skill_code:
        raise PilotInterventionStateError("pilot session skill provenance mismatch")
    if len(assignments) != _EXPECTED_ASSIGNMENT_COUNT:
        raise PilotInterventionStateError("pilot intervention assignment count is invalid")

    first_incomplete: PilotSkillAssignment | None = None
    saw_incomplete = False
    for row in assignments:
        if (
            row.pre_verification_status not in _SCORED_PRE_STATUSES
            or row.pre_submitted_at is None
        ):
            raise PilotInterventionStateError("pilot PRE state is incomplete")
        if row.post_verification_status is not None or row.post_submitted_at is not None:
            raise PilotInterventionStateError("pilot POST state changed during intervention")
        if row.learning_completed_at is None:
            saw_incomplete = True
            if first_incomplete is None:
                first_incomplete = row
        elif saw_incomplete:
            raise PilotInterventionStateError("pilot learning completion is not a prefix")

    if assignment.learning_completed_at is None and assignment is not first_incomplete:
        raise PilotInterventionStateError("session assignment is not the next incomplete item")

    return PilotInterventionContext(
        pilot_skill_assignment_id=assignment.id,
        transfer_excluded_question_ids=(
            assignment.pre_question_id,
            assignment.post_question_id,
        ),
    )


def complete_pilot_learning_assignment(
    db: Session,
    session: TutorSession,
    *,
    received_at: datetime,
) -> PilotInterventionProgression:
    """Complete only the session's persisted assignment and resolve its successor."""

    context = resolve_pilot_intervention_context(db, session)
    with db.no_autoflush:
        assignment = db.get(
            PilotSkillAssignment,
            context.pilot_skill_assignment_id,
        )
        if assignment is None:
            raise PilotInterventionStateError("pilot assignment disappeared")
        enrollment = db.get(PilotEnrollment, assignment.pilot_enrollment_id)
        if enrollment is None:
            raise PilotInterventionStateError("pilot enrollment disappeared")
        assignments = db.scalars(
            select(PilotSkillAssignment)
            .where(PilotSkillAssignment.pilot_enrollment_id == enrollment.id)
            .order_by(PilotSkillAssignment.id)
        ).all()

    assignment_completed_now = assignment.learning_completed_at is None
    next_assignment = next(
        (
            row
            for row in assignments
            if row.learning_completed_at is None
            and row.id != assignment.id
        ),
        None,
    )
    if assignment_completed_now:
        next_assignment = next(
            (row for row in assignments if row.id > assignment.id and row.learning_completed_at is None),
            None,
        )

    next_item: QuestionBankItem | None = None
    next_phase = "post" if next_assignment is None else "intervention"
    if next_assignment is not None:
        next_item = get_question(next_assignment.learning_question_id)
        if (
            next_item is None
            or next_item.id != next_assignment.learning_question_id
            or next_item.skill_code != next_assignment.skill_code
        ):
            raise PilotInterventionConfigurationError(
                "next persisted learning question is missing or mismatched"
            )

    if assignment_completed_now:
        assignment.learning_completed_at = received_at
    if next_phase == "post":
        enrollment.phase = "post"

    return PilotInterventionProgression(
        next_item=next_item,
        enrollment_phase=next_phase,
        assignment_completed_now=assignment_completed_now,
    )

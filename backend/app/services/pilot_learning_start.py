"""Trusted selection for the next persisted pilot LEARNING assignment."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import PilotEnrollment, PilotSkillAssignment
from app.services.question_bank import QuestionBankItem, get_question


_EXPECTED_ASSIGNMENT_COUNT = 9
_SCORED_PRE_STATUSES = {"correct", "incorrect"}


class PilotLearningStartError(RuntimeError):
    """Base class for trusted pilot-learning start failures."""


class PilotLearningStartNotFound(PilotLearningStartError):
    pass


class PilotLearningStartUnavailable(PilotLearningStartError):
    pass


class PilotLearningStartStateError(PilotLearningStartError):
    pass


class PilotLearningStartConfigurationError(PilotLearningStartError):
    pass


@dataclass(frozen=True)
class PilotLearningStart:
    pilot_skill_assignment_id: int
    item: QuestionBankItem


def get_next_pilot_learning_start(
    db: Session,
    *,
    student_id: int,
) -> PilotLearningStart:
    """Return the exact next persisted LEARNING item without mutating state."""

    with db.no_autoflush:
        enrollments = db.scalars(
            select(PilotEnrollment)
            .where(
                PilotEnrollment.student_id == student_id,
                PilotEnrollment.phase != "complete",
            )
            .order_by(PilotEnrollment.id)
        ).all()
        if not enrollments:
            raise PilotLearningStartNotFound("active pilot enrollment not found")
        if len(enrollments) != 1:
            raise PilotLearningStartStateError(
                "student has an ambiguous active pilot enrollment"
            )

        enrollment = enrollments[0]
        if enrollment.phase != "intervention":
            raise PilotLearningStartUnavailable(
                "pilot learning is unavailable in the current phase"
            )

        assignments = db.scalars(
            select(PilotSkillAssignment)
            .where(PilotSkillAssignment.pilot_enrollment_id == enrollment.id)
            .order_by(PilotSkillAssignment.id)
        ).all()

    if len(assignments) != _EXPECTED_ASSIGNMENT_COUNT:
        raise PilotLearningStartStateError(
            "active intervention has an invalid assignment count"
        )

    next_assignment: PilotSkillAssignment | None = None
    saw_incomplete = False
    for assignment in assignments:
        if (
            assignment.pre_verification_status not in _SCORED_PRE_STATUSES
            or assignment.pre_submitted_at is None
        ):
            raise PilotLearningStartStateError(
                "all PRE assignments must be scored before intervention learning"
            )
        if (
            assignment.post_verification_status is not None
            or assignment.post_submitted_at is not None
        ):
            raise PilotLearningStartStateError(
                "POST state must be untouched during intervention"
            )

        if assignment.learning_completed_at is None:
            saw_incomplete = True
            if next_assignment is None:
                next_assignment = assignment
        elif saw_incomplete:
            raise PilotLearningStartStateError(
                "learning completion must form a persisted assignment prefix"
            )

    if next_assignment is None:
        raise PilotLearningStartStateError(
            "all learning assignments are complete while intervention is active"
        )

    item = get_question(next_assignment.learning_question_id)
    if (
        item is None
        or item.id != next_assignment.learning_question_id
        or item.skill_code != next_assignment.skill_code
    ):
        raise PilotLearningStartConfigurationError(
            "persisted learning question is missing or has a skill mismatch"
        )

    return PilotLearningStart(
        pilot_skill_assignment_id=next_assignment.id,
        item=item,
    )

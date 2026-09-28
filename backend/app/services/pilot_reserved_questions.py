from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import PilotEnrollment, PilotSkillAssignment


_EXPECTED_ASSIGNMENT_COUNT = 9
_TERMINAL_PHASE = "complete"


class PilotReservedQuestionStateError(RuntimeError):
    """Raised when active pilot reservation state cannot be trusted."""


def get_active_pilot_reserved_question_ids(
    db: Session,
    *,
    student_id: int,
) -> tuple[str, ...]:
    enrollments = [
        enrollment
        for enrollment in db.scalars(
            select(PilotEnrollment)
            .where(
                PilotEnrollment.student_id == student_id,
                PilotEnrollment.phase != _TERMINAL_PHASE,
            )
            .order_by(PilotEnrollment.id)
        )
        if isinstance(enrollment, PilotEnrollment)
    ]
    if not enrollments:
        return ()
    if len(enrollments) != 1:
        raise PilotReservedQuestionStateError(
            "student has an ambiguous active pilot enrollment"
        )

    assignments = [
        assignment
        for assignment in db.scalars(
            select(PilotSkillAssignment)
            .where(PilotSkillAssignment.pilot_enrollment_id == enrollments[0].id)
            .order_by(PilotSkillAssignment.id)
        )
        if isinstance(assignment, PilotSkillAssignment)
    ]
    if len(assignments) != _EXPECTED_ASSIGNMENT_COUNT:
        raise PilotReservedQuestionStateError(
            "active pilot has incomplete skill assignments"
        )

    reserved_ids: list[str] = []
    for assignment in assignments:
        for question_id in (
            assignment.pre_question_id,
            assignment.learning_question_id,
            assignment.post_question_id,
        ):
            if not isinstance(question_id, str) or not question_id:
                raise PilotReservedQuestionStateError(
                    "active pilot has malformed reserved question IDs"
                )
            reserved_ids.append(question_id)
    return tuple(reserved_ids)

"""Internal persistence seam for Phase 3 pilot enrollment."""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import PilotEnrollment, PilotSkillAssignment
from app.services.pilot_assessment_assignment import assign_pilot_items


def _generate_public_id() -> str:
    return secrets.token_urlsafe(32)


def _generate_assignment_seed() -> str:
    return secrets.token_urlsafe(32)


def create_pilot_enrollment(
    db: Session,
    *,
    student_id: int,
) -> PilotEnrollment:
    existing = db.scalar(
        select(PilotEnrollment).where(
            PilotEnrollment.student_id == student_id,
            PilotEnrollment.phase != "complete",
        )
    )
    if existing is not None:
        raise ValueError("student already has a non-terminal pilot enrollment")

    public_id = _generate_public_id()
    assignment_seed = _generate_assignment_seed()
    assignments = assign_pilot_items(assignment_seed=assignment_seed)

    enrollment = PilotEnrollment(
        public_id=public_id,
        student_id=student_id,
        phase="pre",
    )
    db.add(enrollment)
    db.flush()

    for assignment in assignments:
        db.add(
            PilotSkillAssignment(
                pilot_enrollment_id=enrollment.id,
                skill_code=assignment.skill_code,
                pre_question_id=assignment.pre_question_id,
                learning_question_id=assignment.learning_question_id,
                post_question_id=assignment.post_question_id,
            )
        )

    db.flush()
    return enrollment

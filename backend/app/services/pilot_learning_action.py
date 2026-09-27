"""Pilot-specific composition for reserving assessment questions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.schemas.tutor import TutorState
from app.services.next_learning_action import recommend_next_learning_question
from app.services.pilot_assessment_assignment import assign_pilot_items
from app.services.question_bank import QuestionBankItem


def recommend_next_pilot_learning_question(
    db: Session,
    *,
    student_id: int,
    tutor_state: TutorState,
    now: datetime,
    assignment_seed: str,
) -> QuestionBankItem | None:
    """Reserve pilot assessment items before selecting a learning question."""
    if tutor_state is not TutorState.COMPLETE:
        return None

    assignments = assign_pilot_items(assignment_seed=assignment_seed)
    reserved_question_ids = tuple(
        question_id
        for assignment in assignments
        for question_id in (
            assignment.pre_question_id,
            assignment.post_question_id,
        )
    )
    return recommend_next_learning_question(
        db,
        student_id=student_id,
        tutor_state=tutor_state,
        now=now,
        excluded_question_ids=reserved_question_ids,
    )

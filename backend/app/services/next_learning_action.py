"""Application seam for selecting the next learning action after completion."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Mastery
from app.schemas.tutor import TutorState
from app.services.question_bank import QuestionBankItem
from app.services.question_recommender import (
    MasterySnapshot,
    recommend_next_question,
)


def recommend_next_learning_question(
    db: Session,
    *,
    student_id: int,
    tutor_state: TutorState,
    now: datetime,
    excluded_question_ids: Iterable[str] = (),
) -> QuestionBankItem | None:
    """Select a next authored question only after the tutor session completes."""
    if tutor_state is not TutorState.COMPLETE:
        return None

    db.flush()
    mastery_rows = db.scalars(
        select(Mastery).where(Mastery.student_id == student_id)
    ).all()
    snapshots = tuple(
        MasterySnapshot(
            skill_code=row.skill_code,
            probability=row.probability,
            exposures=row.exposures,
            last_seen_at=row.last_seen_at,
        )
        for row in mastery_rows
    )
    try:
        return recommend_next_question(
            mastery_snapshots=snapshots,
            now=now,
            excluded_question_ids=excluded_question_ids,
        )
    except ValueError as error:
        if str(error) == "no eligible question-bank skills":
            return None
        raise

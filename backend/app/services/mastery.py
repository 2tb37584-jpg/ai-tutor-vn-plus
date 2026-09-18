from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class MasteryUpdate:
    old: float
    new: float


def update_probability(old: float, correct: bool, hint_count: int = 0) -> float:
    """Transparent MVP heuristic. Replace with validated BKT/IRT after collecting data."""
    old = min(0.99, max(0.01, old))
    if correct:
        gain = 0.16 * (1.0 - old)
        hint_penalty = min(0.10, 0.02 * hint_count)
        new = old + gain - hint_penalty
    else:
        new = old - 0.20 * old
    return round(min(0.99, max(0.01, new)), 4)


def record_attempt(db, student_id: int, skill_code: str, correct: bool, hint_count: int = 0) -> MasteryUpdate:
    # Keep persistence imports local so the pure mastery function can be unit-tested without a DB driver.
    from sqlalchemy import select
    from app.models import Mastery

    mastery = db.scalar(
        select(Mastery).where(
            Mastery.student_id == student_id,
            Mastery.skill_code == skill_code,
        )
    )
    if mastery is None:
        mastery = Mastery(student_id=student_id, skill_code=skill_code, probability=0.35)
        db.add(mastery)
        db.flush()

    old = mastery.probability
    mastery.probability = update_probability(old, correct, hint_count)
    mastery.exposures += 1
    mastery.correct_streak = mastery.correct_streak + 1 if correct else 0
    mastery.last_seen_at = datetime.utcnow()
    db.flush()
    return MasteryUpdate(old=old, new=mastery.probability)

"""Pure, deterministic next-best-question selection policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from app.services.question_bank import QuestionBankItem, get_all_questions
from app.services.review_scheduler import schedule_review
from app.services.skill_registry import get_direct_prerequisites, get_skill_definition


_UNSEEN_PROBABILITY = 0.35
_PREREQUISITE_MASTERY_THRESHOLD = 0.80


@dataclass(frozen=True)
class MasterySnapshot:
    skill_code: str
    probability: float
    exposures: int
    last_seen_at: datetime | None


def _validate_snapshots(
    mastery_snapshots: Iterable[MasterySnapshot], now: datetime
) -> dict[str, MasterySnapshot]:
    """Validate and index every supplied snapshot before selection."""
    schedule_review(
        probability=_UNSEEN_PROBABILITY,
        exposures=0,
        last_seen_at=None,
        now=now,
    )

    snapshots_by_skill: dict[str, MasterySnapshot] = {}
    for snapshot in mastery_snapshots:
        if not isinstance(snapshot, MasterySnapshot):
            raise ValueError("mastery snapshots must be MasterySnapshot instances")
        if get_skill_definition(snapshot.skill_code) is None:
            raise ValueError("mastery snapshot has an unknown skill code")
        if snapshot.skill_code in snapshots_by_skill:
            raise ValueError("duplicate mastery snapshot skill code")
        schedule_review(
            probability=snapshot.probability,
            exposures=snapshot.exposures,
            last_seen_at=snapshot.last_seen_at,
            now=now,
        )
        snapshots_by_skill[snapshot.skill_code] = snapshot
    return snapshots_by_skill


def _validate_excluded_question_ids(
    excluded_question_ids: Iterable[str],
) -> frozenset[str]:
    if isinstance(excluded_question_ids, (str, bytes)):
        raise ValueError("excluded question IDs must be an iterable of strings")

    normalized: set[str] = set()
    try:
        for question_id in excluded_question_ids:
            if not isinstance(question_id, str) or question_id == "":
                raise ValueError("excluded question IDs must be non-empty strings")
            normalized.add(question_id)
    except TypeError as exc:
        raise ValueError("excluded question IDs must be an iterable of strings") from exc
    return frozenset(normalized)


def _is_eligible(
    skill_code: str, snapshots_by_skill: dict[str, MasterySnapshot]
) -> bool:
    for prerequisite in get_direct_prerequisites(skill_code):
        snapshot = snapshots_by_skill.get(prerequisite)
        if (
            snapshot is None
            or snapshot.exposures == 0
            or snapshot.probability < _PREREQUISITE_MASTERY_THRESHOLD
        ):
            return False
    return True


def _target_difficulty(*, probability: float, seen: bool) -> int:
    if not seen or probability < 0.50:
        return 1
    if probability < 0.80:
        return 2
    return 3


def recommend_next_question(
    *,
    mastery_snapshots: Iterable[MasterySnapshot],
    now: datetime,
    excluded_question_ids: Iterable[str] = (),
) -> QuestionBankItem:
    """Select the next question using the fixed v1 policy."""
    snapshots_by_skill = _validate_snapshots(mastery_snapshots, now)
    excluded_ids = _validate_excluded_question_ids(excluded_question_ids)
    questions = tuple(
        question
        for question in get_all_questions()
        if question.id not in excluded_ids
    )

    questions_by_skill: dict[str, list[QuestionBankItem]] = {}
    for question in questions:
        questions_by_skill.setdefault(question.skill_code, []).append(question)

    candidates: list[tuple[int, float, int, str, MasterySnapshot]] = []
    for declaration_order, skill_code in enumerate(questions_by_skill):
        if not _is_eligible(skill_code, snapshots_by_skill):
            continue
        snapshot = snapshots_by_skill.get(
            skill_code,
            MasterySnapshot(skill_code, _UNSEEN_PROBABILITY, 0, None),
        )
        seen = snapshot.exposures > 0 and snapshot.last_seen_at is not None
        schedule = schedule_review(
            probability=snapshot.probability,
            exposures=snapshot.exposures,
            last_seen_at=snapshot.last_seen_at,
            now=now,
        )
        priority = 0 if seen and schedule.is_due else 1 if not seen else 2
        candidates.append(
            (priority, snapshot.probability, declaration_order, skill_code, snapshot)
        )

    if not candidates:
        raise ValueError("no eligible question-bank skills")

    _, _, _, skill_code, snapshot = min(candidates, key=lambda candidate: candidate[:3])
    seen = snapshot.exposures > 0 and snapshot.last_seen_at is not None
    target = _target_difficulty(probability=snapshot.probability, seen=seen)
    return min(
        questions_by_skill[skill_code],
        key=lambda question: (abs(question.difficulty - target), question.difficulty),
    )

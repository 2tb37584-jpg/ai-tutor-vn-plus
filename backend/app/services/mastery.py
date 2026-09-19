from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.services.skill_registry import (
    UNKNOWN_SKILL_CODE,
    is_mastery_bearing_skill,
    resolve_skill_code,
)


class MasteryOutcome(str, Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    UNKNOWN = "unknown"


class MasteryEvidenceType(str, Enum):
    DETERMINISTIC_VERIFICATION = "deterministic_verification"
    VERIFIED_TRANSFER = "verified_transfer"
    CONFIRMED_MISCONCEPTION = "confirmed_misconception"
    LLM_JUDGMENT = "llm_judgment"
    CLIENT_CLAIM = "client_claim"


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    UNSUPPORTED = "unsupported"
    DISPUTED = "disputed"


@dataclass(frozen=True)
class MasteryEvidenceEvent:
    student_id: int
    session_id: int | None
    skill_code: str
    outcome: MasteryOutcome
    evidence_type: MasteryEvidenceType
    verification_status: VerificationStatus
    verification_method: str | None = None
    confidence: float = 1.0
    hint_count: int = 0
    misconception_code: str | None = None
    is_transfer: bool = False


@dataclass(frozen=True)
class MasteryUpdate:
    applied: bool
    reason: str
    skill_code: str | None
    old: float | None
    new: float | None


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


def _ineligible(reason: str, skill_code: str | None = None) -> MasteryUpdate:
    return MasteryUpdate(False, reason, skill_code, None, None)


def _eligible_skill(event: MasteryEvidenceEvent) -> tuple[str | None, MasteryUpdate | None]:
    if event.student_id <= 0:
        return None, _ineligible("invalid_student_id")
    if not 0.0 <= event.confidence <= 1.0:
        return None, _ineligible("invalid_confidence")
    if event.hint_count < 0:
        return None, _ineligible("invalid_hint_count")

    canonical_code = resolve_skill_code(event.skill_code)
    if canonical_code == UNKNOWN_SKILL_CODE or not is_mastery_bearing_skill(canonical_code):
        return None, _ineligible("skill_not_mastery_eligible")
    if event.verification_status is not VerificationStatus.VERIFIED:
        return canonical_code, _ineligible("verification_not_verified", canonical_code)
    if event.outcome not in {MasteryOutcome.CORRECT, MasteryOutcome.INCORRECT}:
        return canonical_code, _ineligible("outcome_not_mastery_eligible", canonical_code)
    if event.evidence_type not in {
        MasteryEvidenceType.DETERMINISTIC_VERIFICATION,
        MasteryEvidenceType.VERIFIED_TRANSFER,
    }:
        reason = (
            "client_claim_not_mastery_eligible"
            if event.evidence_type is MasteryEvidenceType.CLIENT_CLAIM
            else "evidence_type_not_mastery_eligible"
        )
        return canonical_code, _ineligible(reason, canonical_code)
    return canonical_code, None


def record_mastery_evidence(db, event: MasteryEvidenceEvent) -> MasteryUpdate:
    """Apply one eligible verified evidence event without committing the transaction."""
    canonical_code, rejected = _eligible_skill(event)
    if rejected is not None:
        return rejected
    assert canonical_code is not None

    from sqlalchemy import select

    from app.models import Mastery

    mastery = db.scalar(
        select(Mastery).where(
            Mastery.student_id == event.student_id,
            Mastery.skill_code == canonical_code,
        )
    )
    if mastery is None:
        mastery = Mastery(
            student_id=event.student_id,
            skill_code=canonical_code,
            probability=0.35,
            exposures=0,
            correct_streak=0,
        )
        db.add(mastery)

    old = mastery.probability
    correct = event.outcome is MasteryOutcome.CORRECT
    mastery.probability = update_probability(old, correct, event.hint_count)
    mastery.exposures += 1
    mastery.correct_streak = mastery.correct_streak + 1 if correct else 0
    mastery.last_seen_at = datetime.utcnow()
    db.flush()
    return MasteryUpdate(True, "mastery_updated", canonical_code, old, mastery.probability)

"""Controlled, deterministic validation for misconception evidence."""

from dataclasses import dataclass
from enum import Enum

from app.services.skill_registry import (
    UNKNOWN_SKILL_CODE,
    SkillDefinition,
    get_controlled_skills,
    is_mastery_bearing_skill,
    resolve_skill_code,
)


class MisconceptionEvidenceStatus(str, Enum):
    SUSPECTED = "suspected"
    CONFIRMED = "confirmed"


class MisconceptionEvidenceSource(str, Enum):
    DETERMINISTIC_RULE = "deterministic_rule"
    LLM_JUDGMENT = "llm_judgment"
    CLIENT_CLAIM = "client_claim"


@dataclass(frozen=True)
class MisconceptionEvidence:
    student_id: int
    session_id: int | None
    skill_code: str
    misconception_code: str
    status: MisconceptionEvidenceStatus
    source: MisconceptionEvidenceSource
    confidence: float


@dataclass(frozen=True)
class MisconceptionEvidenceDecision:
    accepted: bool
    reason: str
    skill_code: str | None
    misconception_code: str | None


def _controlled_skill(skill_label: str) -> SkillDefinition | None:
    canonical_code = resolve_skill_code(skill_label)
    if canonical_code == UNKNOWN_SKILL_CODE or not is_mastery_bearing_skill(canonical_code):
        return None
    return next(
        (skill for skill in get_controlled_skills() if skill.code == canonical_code),
        None,
    )


def get_misconceptions_for_skill(skill_label: str) -> tuple[str, ...]:
    """Return controlled misconception codes for a canonical skill or reviewed alias."""
    skill = _controlled_skill(skill_label)
    return tuple(dict.fromkeys(skill.common_misconceptions)) if skill is not None else ()


def is_controlled_misconception(skill_label: str, misconception_code: str) -> bool:
    """Check exact misconception identity within one controlled skill."""
    return misconception_code in get_misconceptions_for_skill(skill_label)


def _rejected(
    reason: str,
    skill_code: str | None = None,
    misconception_code: str | None = None,
) -> MisconceptionEvidenceDecision:
    return MisconceptionEvidenceDecision(False, reason, skill_code, misconception_code)


def validate_misconception_evidence(
    evidence: MisconceptionEvidence,
) -> MisconceptionEvidenceDecision:
    """Validate controlled misconception evidence without persistence or mastery effects."""
    if evidence.student_id <= 0:
        return _rejected("invalid_student_id")
    if not 0.0 <= evidence.confidence <= 1.0:
        return _rejected("invalid_confidence")

    skill = _controlled_skill(evidence.skill_code)
    if skill is None:
        return _rejected("skill_not_controlled")
    if evidence.misconception_code not in skill.common_misconceptions:
        return _rejected(
            "misconception_not_controlled_for_skill",
            skill.code,
            evidence.misconception_code,
        )

    if (
        evidence.source is MisconceptionEvidenceSource.LLM_JUDGMENT
        and evidence.status is MisconceptionEvidenceStatus.CONFIRMED
    ):
        return _rejected(
            "llm_cannot_confirm_misconception",
            skill.code,
            evidence.misconception_code,
        )
    if (
        evidence.source is MisconceptionEvidenceSource.CLIENT_CLAIM
        and evidence.status is MisconceptionEvidenceStatus.CONFIRMED
    ):
        return _rejected(
            "client_cannot_confirm_misconception",
            skill.code,
            evidence.misconception_code,
        )

    allowed = (
        evidence.source is MisconceptionEvidenceSource.DETERMINISTIC_RULE
        and evidence.status
        in {MisconceptionEvidenceStatus.SUSPECTED, MisconceptionEvidenceStatus.CONFIRMED}
    ) or (
        evidence.source
        in {MisconceptionEvidenceSource.LLM_JUDGMENT, MisconceptionEvidenceSource.CLIENT_CLAIM}
        and evidence.status is MisconceptionEvidenceStatus.SUSPECTED
    )
    if not allowed:
        return _rejected("source_status_not_allowed", skill.code, evidence.misconception_code)

    return MisconceptionEvidenceDecision(
        True,
        "accepted",
        skill.code,
        evidence.misconception_code,
    )

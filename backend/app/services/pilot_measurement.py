"""Pure deterministic calculation for paired pilot assessment summaries."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from statistics import median
from typing import Iterable


_PHASES = frozenset({"pre", "post"})
_OUTCOMES = frozenset(
    {
        "valid",
        "invalid_incomplete",
        "unsupported_verification",
        "indeterminate_verification",
    }
)
_EXCLUDED_OUTCOMES = _OUTCOMES - {"valid"}


@dataclass(frozen=True)
class PilotAssessmentRecord:
    learner_id: str
    phase: str
    outcome: str
    verified_correct_items: int
    valid_scored_items: int


@dataclass(frozen=True)
class PairedLearnerResult:
    learner_id: str
    pre_score: float
    post_score: float
    paired_delta: float


@dataclass(frozen=True)
class PilotMeasurementReport:
    matched_learners: tuple[PairedLearnerResult, ...]
    matched_learner_count: int
    mean_pre_score: float | None
    mean_post_score: float | None
    mean_paired_delta: float | None
    median_paired_delta: float | None
    improved_count: int
    unchanged_count: int
    declined_count: int
    missing_pre: int
    missing_post: int
    invalid_incomplete: int
    unsupported_verification: int
    indeterminate_verification: int


def _validate_record(record: PilotAssessmentRecord) -> None:
    if not isinstance(record, PilotAssessmentRecord):
        raise ValueError("records must contain PilotAssessmentRecord values")
    if not isinstance(record.learner_id, str) or not record.learner_id:
        raise ValueError("learner_id must be a non-empty string")
    if not isinstance(record.phase, str) or record.phase not in _PHASES:
        raise ValueError("phase must be pre or post")
    if not isinstance(record.outcome, str) or record.outcome not in _OUTCOMES:
        raise ValueError("unsupported assessment outcome")
    for value in (record.verified_correct_items, record.valid_scored_items):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("score counts must be integers")
        if value < 0:
            raise ValueError("score counts cannot be negative")
    if record.outcome == "valid":
        if record.valid_scored_items == 0:
            raise ValueError("valid assessment must score at least one item")
        if record.verified_correct_items > record.valid_scored_items:
            raise ValueError("correct items cannot exceed scored items")
    elif record.verified_correct_items or record.valid_scored_items:
        raise ValueError("excluded assessments must have zero score counts")


def _float(value: Fraction) -> float:
    return float(value)


def calculate_pilot_measurement(
    records: Iterable[PilotAssessmentRecord],
) -> PilotMeasurementReport:
    """Calculate a deterministic paired report from trusted assessment summaries."""

    by_learner: dict[str, dict[str, PilotAssessmentRecord]] = {}
    for record in records:
        _validate_record(record)
        phases = by_learner.setdefault(record.learner_id, {})
        if record.phase in phases:
            raise ValueError("duplicate learner/phase record")
        phases[record.phase] = record

    missing_pre = sum("pre" not in phases for phases in by_learner.values())
    missing_post = sum("post" not in phases for phases in by_learner.values())
    invalid_incomplete = sum(
        any(record.outcome == "invalid_incomplete" for record in phases.values())
        for phases in by_learner.values()
    )
    unsupported_verification = sum(
        any(record.outcome == "unsupported_verification" for record in phases.values())
        for phases in by_learner.values()
    )
    indeterminate_verification = sum(
        any(record.outcome == "indeterminate_verification" for record in phases.values())
        for phases in by_learner.values()
    )

    exact_results: list[tuple[str, Fraction, Fraction, Fraction]] = []
    for learner_id in sorted(by_learner):
        phases = by_learner[learner_id]
        pre = phases.get("pre")
        post = phases.get("post")
        if (
            pre is None
            or post is None
            or pre.outcome != "valid"
            or post.outcome != "valid"
        ):
            continue
        pre_score = Fraction(pre.verified_correct_items, pre.valid_scored_items)
        post_score = Fraction(post.verified_correct_items, post.valid_scored_items)
        exact_results.append((learner_id, pre_score, post_score, post_score - pre_score))

    matched_learners = tuple(
        PairedLearnerResult(
            learner_id=learner_id,
            pre_score=_float(pre_score),
            post_score=_float(post_score),
            paired_delta=_float(delta),
        )
        for learner_id, pre_score, post_score, delta in exact_results
    )
    deltas = [delta for _, _, _, delta in exact_results]
    if not exact_results:
        return PilotMeasurementReport(
            matched_learners=matched_learners,
            matched_learner_count=0,
            mean_pre_score=None,
            mean_post_score=None,
            mean_paired_delta=None,
            median_paired_delta=None,
            improved_count=0,
            unchanged_count=0,
            declined_count=0,
            missing_pre=missing_pre,
            missing_post=missing_post,
            invalid_incomplete=invalid_incomplete,
            unsupported_verification=unsupported_verification,
            indeterminate_verification=indeterminate_verification,
        )

    pre_scores = [pre_score for _, pre_score, _, _ in exact_results]
    post_scores = [post_score for _, _, post_score, _ in exact_results]
    return PilotMeasurementReport(
        matched_learners=matched_learners,
        matched_learner_count=len(exact_results),
        mean_pre_score=_float(sum(pre_scores, Fraction()) / len(pre_scores)),
        mean_post_score=_float(sum(post_scores, Fraction()) / len(post_scores)),
        mean_paired_delta=_float(sum(deltas, Fraction()) / len(deltas)),
        median_paired_delta=_float(median(deltas)),
        improved_count=sum(delta > 0 for delta in deltas),
        unchanged_count=sum(delta == 0 for delta in deltas),
        declined_count=sum(delta < 0 for delta in deltas),
        missing_pre=missing_pre,
        missing_post=missing_post,
        invalid_incomplete=invalid_incomplete,
        unsupported_verification=unsupported_verification,
        indeterminate_verification=indeterminate_verification,
    )

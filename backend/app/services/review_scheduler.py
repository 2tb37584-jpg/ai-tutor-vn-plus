"""Pure deterministic review scheduling policy."""

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class ReviewSchedule:
    due_at: datetime
    interval_days: int
    is_due: bool
    reason: str


def _is_timezone_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def schedule_review(
    *,
    probability: float,
    exposures: int,
    last_seen_at: datetime | None,
    now: datetime,
) -> ReviewSchedule:
    if (
        isinstance(probability, bool)
        or not isinstance(probability, (int, float))
        or not 0.0 <= probability <= 1.0
    ):
        raise ValueError("probability must be between 0.0 and 1.0")
    if isinstance(exposures, bool) or not isinstance(exposures, int) or exposures < 0:
        raise ValueError("exposures must be a non-negative integer")
    if last_seen_at is not None and not isinstance(last_seen_at, datetime):
        raise ValueError("last_seen_at must be a datetime or None")
    if not isinstance(now, datetime):
        raise ValueError("now must be a datetime")
    if last_seen_at is not None and (
        _is_timezone_aware(last_seen_at) != _is_timezone_aware(now)
    ):
        raise ValueError("last_seen_at and now must both be naive or timezone-aware")

    if exposures == 0 or last_seen_at is None:
        return ReviewSchedule(now, 0, True, "unseen")
    if probability < 0.50:
        interval_days, reason = 1, "low_mastery"
    elif probability < 0.80:
        interval_days, reason = 3, "developing_mastery"
    else:
        interval_days, reason = 7, "strong_mastery"

    due_at = last_seen_at + timedelta(days=interval_days)
    return ReviewSchedule(due_at, interval_days, now >= due_at, reason)

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from app.services.review_scheduler import ReviewSchedule, schedule_review


NOW = datetime(2026, 9, 23, 10, 0, 0)


def test_review_schedule_is_frozen() -> None:
    schedule = ReviewSchedule(NOW, 1, False, "low_mastery")

    with pytest.raises(FrozenInstanceError):
        schedule.interval_days = 3  # type: ignore[misc]


def test_unseen_exposure_is_due_immediately() -> None:
    schedule = schedule_review(
        probability=0.9,
        exposures=0,
        last_seen_at=NOW - timedelta(days=10),
        now=NOW,
    )

    assert schedule == ReviewSchedule(NOW, 0, True, "unseen")


def test_missing_last_seen_is_due_immediately() -> None:
    schedule = schedule_review(
        probability=0.9,
        exposures=4,
        last_seen_at=None,
        now=NOW,
    )

    assert schedule == ReviewSchedule(NOW, 0, True, "unseen")


@pytest.mark.parametrize(
    ("probability", "interval_days", "reason"),
    [
        (0.00, 1, "low_mastery"),
        (0.49, 1, "low_mastery"),
        (0.50, 3, "developing_mastery"),
        (0.79, 3, "developing_mastery"),
        (0.80, 7, "strong_mastery"),
        (1.00, 7, "strong_mastery"),
    ],
)
def test_mastery_intervals_include_policy_boundaries(
    probability: float,
    interval_days: int,
    reason: str,
) -> None:
    schedule = schedule_review(
        probability=probability,
        exposures=1,
        last_seen_at=NOW,
        now=NOW,
    )

    assert schedule.interval_days == interval_days
    assert schedule.reason == reason
    assert schedule.due_at == NOW + timedelta(days=interval_days)
    assert schedule.is_due is False


@pytest.mark.parametrize(
    ("now_offset", "is_due"),
    [
        (timedelta(days=2, seconds=86399), False),
        (timedelta(days=3), True),
        (timedelta(days=4), True),
    ],
)
def test_due_boundary_uses_greater_than_or_equal(
    now_offset: timedelta,
    is_due: bool,
) -> None:
    schedule = schedule_review(
        probability=0.5,
        exposures=1,
        last_seen_at=NOW,
        now=NOW + now_offset,
    )

    assert schedule.is_due is is_due


@pytest.mark.parametrize("probability", [-0.01, 1.01, True, False])
def test_invalid_probability_is_rejected(probability: object) -> None:
    with pytest.raises(ValueError):
        schedule_review(
            probability=probability,
            exposures=1,
            last_seen_at=NOW,
            now=NOW,
        )


@pytest.mark.parametrize("exposures", [-1, True, False, 1.5, "1"])
def test_invalid_exposures_are_rejected(exposures: object) -> None:
    with pytest.raises(ValueError):
        schedule_review(
            probability=0.5,
            exposures=exposures,
            last_seen_at=NOW,
            now=NOW,
        )


@pytest.mark.parametrize("last_seen_at", ["2026-09-23", 1])
def test_invalid_last_seen_is_rejected(last_seen_at: object) -> None:
    with pytest.raises(ValueError):
        schedule_review(
            probability=0.5,
            exposures=1,
            last_seen_at=last_seen_at,
            now=NOW,
        )


@pytest.mark.parametrize("now", ["2026-09-23", 1])
def test_invalid_now_is_rejected(now: object) -> None:
    with pytest.raises(ValueError):
        schedule_review(
            probability=0.5,
            exposures=1,
            last_seen_at=NOW,
            now=now,
        )


@pytest.mark.parametrize(
    ("probability", "exposures"),
    [(-0.01, 0), (1.01, 0), (0.5, -1), (0.5, True)],
)
def test_unseen_records_do_not_skip_validation(
    probability: float,
    exposures: int,
) -> None:
    with pytest.raises(ValueError):
        schedule_review(
            probability=probability,
            exposures=exposures,
            last_seen_at=None,
            now=NOW,
        )


def test_naive_and_aware_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError):
        schedule_review(
            probability=0.5,
            exposures=1,
            last_seen_at=NOW,
            now=NOW.replace(tzinfo=UTC),
        )


def test_naive_datetimes_are_supported() -> None:
    schedule = schedule_review(
        probability=0.5,
        exposures=1,
        last_seen_at=NOW,
        now=NOW + timedelta(days=3),
    )

    assert schedule.due_at.tzinfo is None
    assert schedule.is_due is True


def test_timezone_aware_datetimes_are_supported_without_conversion() -> None:
    aware_now = NOW.replace(tzinfo=UTC)
    schedule = schedule_review(
        probability=0.8,
        exposures=1,
        last_seen_at=aware_now,
        now=aware_now + timedelta(days=7),
    )

    assert schedule.due_at.tzinfo is UTC
    assert schedule.due_at == aware_now + timedelta(days=7)
    assert schedule.is_due is True

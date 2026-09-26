from __future__ import annotations

import pytest

from app.services.pilot_measurement import (
    PairedLearnerResult,
    PilotAssessmentRecord,
    calculate_pilot_measurement,
)


def record(
    learner_id: str,
    phase: str,
    outcome: str = "valid",
    correct: int = 0,
    scored: int = 1,
) -> PilotAssessmentRecord:
    return PilotAssessmentRecord(learner_id, phase, outcome, correct, scored)


def test_one_matched_learner_calculates_scores_and_delta() -> None:
    report = calculate_pilot_measurement(
        [record("learner-a", "pre", correct=1, scored=2), record("learner-a", "post", correct=3, scored=4)]
    )

    assert report.matched_learner_count == 1
    assert report.matched_learners == (PairedLearnerResult("learner-a", 0.5, 0.75, 0.25),)
    assert report.mean_pre_score == 0.5
    assert report.mean_post_score == 0.75
    assert report.mean_paired_delta == 0.25
    assert report.median_paired_delta == 0.25
    assert report.improved_count == 1


def test_multiple_learners_report_means_median_and_classification() -> None:
    report = calculate_pilot_measurement(
        [
            record("learner-c", "pre", correct=1, scored=2),
            record("learner-c", "post", correct=1, scored=2),
            record("learner-a", "pre", correct=1, scored=1),
            record("learner-a", "post", correct=0, scored=1),
            record("learner-b", "pre", correct=0, scored=2),
            record("learner-b", "post", correct=2, scored=2),
        ]
    )

    assert report.mean_pre_score == pytest.approx(0.5)
    assert report.mean_post_score == pytest.approx(0.5)
    assert report.mean_paired_delta == 0
    assert report.median_paired_delta == 0
    assert (report.improved_count, report.unchanged_count, report.declined_count) == (1, 1, 1)
    assert [item.learner_id for item in report.matched_learners] == ["learner-a", "learner-b", "learner-c"]


def test_even_cohort_median_is_deterministic() -> None:
    report = calculate_pilot_measurement(
        [
            record("learner-a", "pre", correct=0, scored=1),
            record("learner-a", "post", correct=1, scored=1),
            record("learner-b", "pre", correct=1, scored=1),
            record("learner-b", "post", correct=0, scored=1),
        ]
    )

    assert report.median_paired_delta == 0


def test_exclusions_are_unique_per_learner_and_not_matched() -> None:
    report = calculate_pilot_measurement(
        [
            record("learner-a", "post", "invalid_incomplete", 0, 0),
            record("learner-b", "pre", "unsupported_verification", 0, 0),
            record("learner-b", "post", "indeterminate_verification", 0, 0),
            record("learner-c", "pre", correct=1),
            record("learner-c", "post", correct=1),
            record("learner-d", "pre", correct=1),
        ]
    )

    assert report.matched_learner_count == 1
    assert report.missing_pre == 1
    assert report.missing_post == 1
    assert report.invalid_incomplete == 1
    assert report.unsupported_verification == 1
    assert report.indeterminate_verification == 1


def test_excluded_outcome_count_is_unique_per_learner() -> None:
    report = calculate_pilot_measurement(
        [
            record("learner-a", "pre", "invalid_incomplete", 0, 0),
            record("learner-a", "post", "invalid_incomplete", 0, 0),
        ]
    )

    assert report.invalid_incomplete == 1


def test_empty_matched_cohort_has_none_aggregates() -> None:
    report = calculate_pilot_measurement([record("learner-a", "pre", "invalid_incomplete", 0, 0)])

    assert report.matched_learner_count == 0
    assert report.mean_pre_score is None
    assert report.mean_post_score is None
    assert report.mean_paired_delta is None
    assert report.median_paired_delta is None
    assert (report.improved_count, report.unchanged_count, report.declined_count) == (0, 0, 0)


@pytest.mark.parametrize(
    ("records", "message"),
    [
        ([record("", "pre")], "learner_id"),
        ([record("learner-a", "practice")], "phase"),
        ([record("learner-a", "pre", "correct")], "outcome"),
        ([record("learner-a", "pre", correct=-1)], "negative"),
        ([record("learner-a", "pre", correct=2, scored=1)], "exceed"),
        ([record("learner-a", "pre", correct=0, scored=0)], "at least"),
        ([record("learner-a", "pre", "invalid_incomplete", 1, 0)], "zero"),
        ([record("learner-a", "pre"), record("learner-a", "pre")], "duplicate"),
    ],
)
def test_malformed_records_raise_value_error(records: list[PilotAssessmentRecord], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        calculate_pilot_measurement(records)


@pytest.mark.parametrize(
    ("phase", "outcome", "message"),
    [(["pre"], "valid", "phase"), ("pre", ["valid"], "outcome")],
)
def test_non_string_phase_or_outcome_raises_value_error(
    phase: object, outcome: object, message: str
) -> None:
    malformed = PilotAssessmentRecord("learner-a", phase, outcome, 1, 1)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match=message):
        calculate_pilot_measurement([malformed])


@pytest.mark.parametrize("field", ["verified_correct_items", "valid_scored_items"])
def test_boolean_score_counts_are_rejected(field: str) -> None:
    values = {"learner_id": "learner-a", "phase": "pre", "outcome": "valid", "verified_correct_items": 1, "valid_scored_items": 1}
    values[field] = True

    with pytest.raises(ValueError, match="integers"):
        calculate_pilot_measurement([PilotAssessmentRecord(**values)])


def test_input_order_does_not_change_report_and_output_is_learner_safe() -> None:
    records = [
        record("learner-b", "post", correct=2, scored=2),
        record("learner-a", "pre", correct=1, scored=2),
        record("learner-b", "pre", correct=1, scored=2),
        record("learner-a", "post", correct=2, scored=2),
    ]

    assert calculate_pilot_measurement(records) == calculate_pilot_measurement(reversed(records))
    assert set(calculate_pilot_measurement(records).matched_learners[0].__dict__) == {
        "learner_id",
        "pre_score",
        "post_score",
        "paired_delta",
    }

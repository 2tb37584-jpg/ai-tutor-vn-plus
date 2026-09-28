"""Aggregate-only operational report for persisted pilot assessments."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.entities import PilotEnrollment
from app.services.pilot_measurement import calculate_pilot_measurement
from app.services.pilot_measurement_projection import (
    PilotMeasurementProjectionError,
    project_pilot_assessment_records,
)


@dataclass(frozen=True)
class PilotAggregateMeasurementReport:
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


def build_aggregate_pilot_measurement_report(
    db: Session,
) -> PilotAggregateMeasurementReport:
    """Project all persisted enrollments and calculate one cohort aggregate."""

    records = []
    with db.no_autoflush:
        enrollment_ids = db.scalars(
            select(PilotEnrollment.id).order_by(PilotEnrollment.id)
        ).all()
        for enrollment_id in enrollment_ids:
            records.extend(
                project_pilot_assessment_records(db, enrollment_id=enrollment_id)
            )

    measurement = calculate_pilot_measurement(tuple(records))
    return PilotAggregateMeasurementReport(
        matched_learner_count=measurement.matched_learner_count,
        mean_pre_score=measurement.mean_pre_score,
        mean_post_score=measurement.mean_post_score,
        mean_paired_delta=measurement.mean_paired_delta,
        median_paired_delta=measurement.median_paired_delta,
        improved_count=measurement.improved_count,
        unchanged_count=measurement.unchanged_count,
        declined_count=measurement.declined_count,
        missing_pre=measurement.missing_pre,
        missing_post=measurement.missing_post,
        invalid_incomplete=measurement.invalid_incomplete,
        unsupported_verification=measurement.unsupported_verification,
        indeterminate_verification=measurement.indeterminate_verification,
    )


def serialize_aggregate_report(report: PilotAggregateMeasurementReport) -> str:
    """Serialize only the public-to-operations aggregate fields deterministically."""

    return json.dumps(
        asdict(report),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def main() -> int:
    try:
        with SessionLocal() as db:
            report = build_aggregate_pilot_measurement_report(db)
    except PilotMeasurementProjectionError:
        print("Pilot measurement report unavailable", file=sys.stderr)
        return 1

    print(serialize_aggregate_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

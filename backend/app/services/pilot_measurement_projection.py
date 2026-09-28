"""Read-only projection of persisted pilot assessments into M09-22 records."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import PilotEnrollment, PilotSkillAssignment
from app.services.pilot_measurement import PilotAssessmentRecord


_ASSESSMENT_SIZE = 9
_SCORED_STATUSES = frozenset({"correct", "incorrect"})
_RETRYABLE_STATUSES = {
    "unsupported": "unsupported_verification",
    "indeterminate": "indeterminate_verification",
}


class PilotMeasurementProjectionError(RuntimeError):
    """Base class for expected persisted-assessment projection errors."""


class PilotMeasurementProjectionNotFound(PilotMeasurementProjectionError):
    """The requested pilot enrollment does not exist."""


class PilotMeasurementProjectionStateError(PilotMeasurementProjectionError):
    """The enrollment cannot be safely paired to a measurement learner."""


def _phase_record(
    *,
    learner_id: str,
    phase: str,
    statuses: list[str | None],
    submitted_at: list[object | None],
) -> PilotAssessmentRecord | None:
    states: list[str] = []
    for status, timestamp in zip(statuses, submitted_at, strict=True):
        if status is None and timestamp is None:
            states.append("untouched")
        elif (
            isinstance(status, str)
            and status in _SCORED_STATUSES
            and timestamp is not None
        ):
            states.append("scored")
        elif (
            isinstance(status, str)
            and status in _RETRYABLE_STATUSES
            and timestamp is None
        ):
            states.append(status)
        else:
            states.append("invalid")

    if all(state == "untouched" for state in states):
        return None

    if len(states) == _ASSESSMENT_SIZE and all(state == "scored" for state in states):
        return PilotAssessmentRecord(
            learner_id=learner_id,
            phase=phase,
            outcome="valid",
            verified_correct_items=sum(status == "correct" for status in statuses),
            valid_scored_items=_ASSESSMENT_SIZE,
        )

    outcome = "invalid_incomplete"
    scored_prefix = 0
    while scored_prefix < len(states) and states[scored_prefix] == "scored":
        scored_prefix += 1

    if scored_prefix < len(states) and states[scored_prefix] in _RETRYABLE_STATUSES:
        retryable_status = states[scored_prefix]
        tail = states[scored_prefix + 1 :]
        if all(state == "untouched" for state in tail):
            outcome = _RETRYABLE_STATUSES[retryable_status]

    return PilotAssessmentRecord(
        learner_id=learner_id,
        phase=phase,
        outcome=outcome,
        verified_correct_items=0,
        valid_scored_items=0,
    )


def project_pilot_assessment_records(
    db: Session,
    *,
    enrollment_id: int,
) -> tuple[PilotAssessmentRecord, ...]:
    """Project persisted PRE/POST statuses without mutating or scoring answers."""

    with db.no_autoflush:
        enrollment = db.scalar(
            select(PilotEnrollment).where(PilotEnrollment.id == enrollment_id)
        )
        if enrollment is None:
            raise PilotMeasurementProjectionNotFound("pilot enrollment not found")

        learner_id = enrollment.public_id
        if not isinstance(learner_id, str) or not learner_id.strip():
            raise PilotMeasurementProjectionStateError(
                "pilot enrollment public ID must be a non-empty string"
            )

        assignments = list(
            db.scalars(
                select(PilotSkillAssignment)
                .where(PilotSkillAssignment.pilot_enrollment_id == enrollment_id)
                .order_by(PilotSkillAssignment.id)
            ).all()
        )

    if len(assignments) != _ASSESSMENT_SIZE:
        return tuple(
            PilotAssessmentRecord(
                learner_id=learner_id,
                phase=phase,
                outcome="invalid_incomplete",
                verified_correct_items=0,
                valid_scored_items=0,
            )
            for phase in ("pre", "post")
        )

    records: list[PilotAssessmentRecord] = []
    for phase, status_attribute, submitted_attribute in (
        ("pre", "pre_verification_status", "pre_submitted_at"),
        ("post", "post_verification_status", "post_submitted_at"),
    ):
        record = _phase_record(
            learner_id=learner_id,
            phase=phase,
            statuses=[getattr(assignment, status_attribute) for assignment in assignments],
            submitted_at=[
                getattr(assignment, submitted_attribute) for assignment in assignments
            ],
        )
        if record is not None:
            records.append(record)

    return tuple(records)

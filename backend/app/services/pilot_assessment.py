"""Deterministic internal PRE/POST pilot assessment domain service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import PilotEnrollment, PilotSkillAssignment
from app.services.question_bank import (
    QuestionBankItem,
    get_question,
    verification_request_for_candidate,
)
from app.services.verifier import VerificationStatus, verify


class PilotAssessmentError(Exception):
    """Base class for deterministic pilot assessment domain failures."""


class PilotAssessmentNotFound(PilotAssessmentError):
    pass


class PilotAssessmentUnavailable(PilotAssessmentError):
    pass


class PilotAssessmentQuestionMismatch(PilotAssessmentError):
    pass


class PilotAssessmentStateError(PilotAssessmentError):
    pass


class PilotAssessmentConfigurationError(PilotAssessmentError):
    pass


@dataclass(frozen=True)
class PilotAssessmentItem:
    phase: str
    question_id: str
    skill_code: str
    problem_text: str
    difficulty: int


@dataclass(frozen=True)
class PilotAssessmentSubmissionResult:
    verification_status: VerificationStatus
    accepted: bool
    phase_complete: bool
    enrollment_phase: str


_PHASES = {"pre", "intervention", "post", "complete"}
_SCORED_STATUSES = {VerificationStatus.CORRECT, VerificationStatus.INCORRECT}


def _get_enrollment(db: Session, enrollment_id: int) -> PilotEnrollment:
    enrollment = db.get(PilotEnrollment, enrollment_id)
    if enrollment is None:
        raise PilotAssessmentNotFound(
            f"Pilot enrollment not found: {enrollment_id}"
        )
    return enrollment


def _assignments(db: Session, enrollment_id: int) -> list[PilotSkillAssignment]:
    assignments = db.scalars(
        select(PilotSkillAssignment)
        .where(PilotSkillAssignment.pilot_enrollment_id == enrollment_id)
        .order_by(PilotSkillAssignment.id)
    ).all()
    if not assignments:
        raise PilotAssessmentConfigurationError(
            "Pilot enrollment has no persisted skill assignments"
        )
    return assignments


def _status_is_scored(status: str | None) -> bool:
    return status in {item.value for item in _SCORED_STATUSES}


def _validate_assignment_state(
    assignments: list[PilotSkillAssignment],
    *,
    phase: str,
) -> None:
    valid_statuses = {None, *(item.value for item in VerificationStatus)}
    for assignment in assignments:
        for role in ("pre", "post"):
            status = getattr(assignment, f"{role}_verification_status")
            submitted_at = getattr(assignment, f"{role}_submitted_at")
            if status not in valid_statuses:
                raise PilotAssessmentStateError(
                    f"{role} verification has an invalid status"
                )
            if submitted_at is not None and not _status_is_scored(status):
                raise PilotAssessmentStateError(
                    f"{role} submission has an invalid verification status"
                )
            if _status_is_scored(status) and submitted_at is None:
                raise PilotAssessmentStateError(
                    f"scored {role.upper()} verification is missing its submission timestamp"
                )
            if status in {"unsupported", "indeterminate"} and submitted_at is not None:
                raise PilotAssessmentStateError(
                    f"{role} retryable verification has a submission timestamp"
                )

    def validate_prefix(role: str) -> None:
        saw_incomplete = False
        for assignment in assignments:
            status = getattr(assignment, f"{role}_verification_status")
            submitted_at = getattr(assignment, f"{role}_submitted_at")
            completed = submitted_at is not None and _status_is_scored(status)
            retryable = status in {"unsupported", "indeterminate"} and submitted_at is None
            untouched = status is None and submitted_at is None
            if completed:
                if saw_incomplete:
                    raise PilotAssessmentStateError(
                        f"{role.upper()} assignments are completed out of order"
                    )
            elif retryable or untouched:
                if saw_incomplete and not untouched:
                    raise PilotAssessmentStateError(
                        f"{role.upper()} assignments are completed out of order"
                    )
                saw_incomplete = True
            else:
                raise PilotAssessmentStateError(
                    f"{role.upper()} assignment state is invalid"
                )

    validate_prefix("pre")
    validate_prefix("post")

    if phase == "pre":
        if any(assignment.learning_completed_at is not None for assignment in assignments):
            raise PilotAssessmentStateError(
                "Learning cannot be complete while enrollment is in PRE"
            )
        if any(
            assignment.post_verification_status is not None
            or assignment.post_submitted_at is not None
            for assignment in assignments
        ):
            raise PilotAssessmentStateError(
                "POST state is not allowed while enrollment is in PRE"
            )
    elif phase == "intervention":
        if not _pre_complete(assignments):
            raise PilotAssessmentStateError(
                "PRE assignments must be complete before intervention"
            )
        if any(
            assignment.post_verification_status is not None
            or assignment.post_submitted_at is not None
            for assignment in assignments
        ):
            raise PilotAssessmentStateError(
                "POST state is not allowed during intervention"
            )
    elif phase == "post":
        if not _pre_complete(assignments) or not _learning_complete(assignments):
            raise PilotAssessmentStateError(
                "POST assessment prerequisites are incomplete"
            )
    elif phase == "complete":
        if not _pre_complete(assignments) or not _learning_complete(assignments):
            raise PilotAssessmentStateError(
                "Completed enrollment has incomplete prerequisites"
            )
        if not all(
            assignment.post_submitted_at is not None
            and _status_is_scored(assignment.post_verification_status)
            for assignment in assignments
        ):
            raise PilotAssessmentStateError(
                "Completed enrollment has incomplete POST assignments"
            )


def _pre_complete(assignments: list[PilotSkillAssignment]) -> bool:
    return all(
        assignment.pre_submitted_at is not None
        and _status_is_scored(assignment.pre_verification_status)
        for assignment in assignments
    )


def _learning_complete(assignments: list[PilotSkillAssignment]) -> bool:
    return all(assignment.learning_completed_at is not None for assignment in assignments)


def _safe_item(
    *,
    phase: str,
    question_id: str,
    skill_code: str,
) -> PilotAssessmentItem:
    question: QuestionBankItem | None = get_question(question_id)
    if question is None or question.skill_code != skill_code:
        raise PilotAssessmentConfigurationError(
            "Persisted assessment question is missing or has a skill mismatch"
        )
    return PilotAssessmentItem(
        phase=phase,
        question_id=question.id,
        skill_code=question.skill_code,
        problem_text=question.problem_text,
        difficulty=question.difficulty,
    )


def get_current_pilot_assessment_item(
    db: Session,
    *,
    enrollment_id: int,
) -> PilotAssessmentItem | None:
    enrollment = _get_enrollment(db, enrollment_id)
    if enrollment.phase not in _PHASES:
        raise PilotAssessmentStateError("Pilot enrollment has an invalid phase")
    assignments = _assignments(db, enrollment_id)
    _validate_assignment_state(assignments, phase=enrollment.phase)
    if enrollment.phase in {"intervention", "complete"}:
        return None
    if enrollment.phase == "pre":
        incomplete = next(
            (
                assignment
                for assignment in assignments
                if assignment.pre_submitted_at is None
            ),
            None,
        )
        if incomplete is None:
            raise PilotAssessmentStateError(
                "PRE assignments are complete but enrollment is still in PRE"
            )
        return _safe_item(
            phase="pre",
            question_id=incomplete.pre_question_id,
            skill_code=incomplete.skill_code,
        )

    if not _pre_complete(assignments) or not _learning_complete(assignments):
        raise PilotAssessmentStateError(
            "POST assessment prerequisites are incomplete"
        )
    incomplete = next(
        (
            assignment
            for assignment in assignments
            if assignment.post_submitted_at is None
        ),
        None,
    )
    if incomplete is None:
        raise PilotAssessmentStateError(
            "POST assignments are complete but enrollment is still in POST"
        )
    return _safe_item(
        phase="post",
        question_id=incomplete.post_question_id,
        skill_code=incomplete.skill_code,
    )


def submit_pilot_assessment_response(
    db: Session,
    *,
    enrollment_id: int,
    question_id: str,
    candidate: str,
    now: datetime,
) -> PilotAssessmentSubmissionResult:
    enrollment = _get_enrollment(db, enrollment_id)
    current = get_current_pilot_assessment_item(db, enrollment_id=enrollment_id)
    if current is None:
        raise PilotAssessmentUnavailable(
            "Pilot enrollment has no currently available assessment item"
        )
    if question_id != current.question_id:
        raise PilotAssessmentQuestionMismatch(
            "Submitted question is not the current pilot assessment item"
        )

    question = get_question(current.question_id)
    if question is None or question.skill_code != current.skill_code:
        raise PilotAssessmentConfigurationError(
            "Current assessment question is missing or has a skill mismatch"
        )
    try:
        verification = verify(verification_request_for_candidate(question, candidate))
    except ValueError as error:
        raise PilotAssessmentConfigurationError(
            "Current assessment question cannot be verified"
        ) from error

    role = current.phase
    setattr(enrollment_assignment := next(
        assignment
        for assignment in _assignments(db, enrollment_id)
        if getattr(assignment, f"{role}_question_id") == current.question_id
    ), f"{role}_verification_status", verification.status.value)

    accepted = verification.status in _SCORED_STATUSES
    phase_complete = False
    if accepted:
        setattr(enrollment_assignment, f"{role}_submitted_at", now)
        assignments = _assignments(db, enrollment_id)
        if role == "pre" and _pre_complete(assignments):
            enrollment.phase = "intervention"
            phase_complete = True
        elif role == "post" and all(
            assignment.post_submitted_at is not None
            and _status_is_scored(assignment.post_verification_status)
            for assignment in assignments
        ):
            enrollment.phase = "complete"
            phase_complete = True

    db.flush()
    return PilotAssessmentSubmissionResult(
        verification_status=verification.status,
        accepted=accepted,
        phase_complete=phase_complete,
        enrollment_phase=enrollment.phase,
    )

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User, Student, Mastery
from app.models.entities import PilotEnrollment, PilotSkillAssignment
from app.schemas.student import StudentCreate, StudentOut, MasteryOut
from app.schemas.pilot import (
    PilotAssessmentItemOut,
    PilotAssessmentSubmissionIn,
    PilotStatusOut,
)
from app.services.pilot_enrollment import create_pilot_enrollment
from app.services.pilot_assessment import (
    PilotAssessmentError,
    PilotAssessmentConfigurationError,
    PilotAssessmentNotFound,
    PilotAssessmentQuestionMismatch,
    PilotAssessmentStateError,
    PilotAssessmentUnavailable,
    get_current_pilot_assessment_item,
    submit_pilot_assessment_response,
)

router = APIRouter(prefix="/students", tags=["students"])


@router.get("", response_model=list[StudentOut])
def list_students(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list(db.scalars(select(Student).where(Student.owner_id == user.id).order_by(Student.id)))


@router.post("", response_model=StudentOut, status_code=201)
def create_student(payload: StudentCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    student = Student(owner_id=user.id, **payload.model_dump())
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


@router.get("/{student_id}/mastery", response_model=list[MasteryOut])
def get_mastery(student_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    student = db.get(Student, student_id)
    if student is None or student.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Student not found")
    return list(db.scalars(select(Mastery).where(Mastery.student_id == student_id).order_by(Mastery.probability)))


def _owned_student(db: Session, *, student_id: int, user: User) -> Student:
    student = db.get(Student, student_id)
    if student is None or student.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Student not found")
    return student


def _current_or_latest_pilot(db: Session, *, student_id: int) -> PilotEnrollment | None:
    active = db.scalar(
        select(PilotEnrollment)
        .where(
            PilotEnrollment.student_id == student_id,
            PilotEnrollment.phase != "complete",
        )
        .order_by(PilotEnrollment.id.desc())
    )
    if active is not None:
        return active
    return db.scalar(
        select(PilotEnrollment)
        .where(
            PilotEnrollment.student_id == student_id,
            PilotEnrollment.phase == "complete",
        )
        .order_by(PilotEnrollment.created_at.desc(), PilotEnrollment.id.desc())
    )


def _active_pilot(db: Session, *, student_id: int) -> PilotEnrollment | None:
    return db.scalar(
        select(PilotEnrollment)
        .where(
            PilotEnrollment.student_id == student_id,
            PilotEnrollment.phase != "complete",
        )
        .order_by(PilotEnrollment.id.desc())
    )


def _pilot_status(db: Session, enrollment: PilotEnrollment) -> PilotStatusOut:
    assignments = db.scalars(
        select(PilotSkillAssignment).where(
            PilotSkillAssignment.pilot_enrollment_id == enrollment.id
        )
    ).all()
    return PilotStatusOut(
        pilot_id=enrollment.public_id,
        phase=enrollment.phase,
        skills_total=len(assignments),
        pre_completed_skills=sum(
            assignment.pre_submitted_at is not None for assignment in assignments
        ),
        learning_completed_skills=sum(
            assignment.learning_completed_at is not None for assignment in assignments
        ),
        post_completed_skills=sum(
            assignment.post_submitted_at is not None for assignment in assignments
        ),
    )


def _is_active_pilot_integrity_conflict(error: IntegrityError) -> bool:
    message = str(error.orig or error)
    return (
        "uq_pilot_enrollments_nonterminal_student" in message
        or "UNIQUE constraint failed: pilot_enrollments.student_id" in message
    )


def _is_active_pilot_service_conflict(error: ValueError) -> bool:
    return str(error) == "student already has a non-terminal pilot enrollment"


@router.post(
    "/{student_id}/pilot",
    response_model=PilotStatusOut,
    status_code=status.HTTP_201_CREATED,
)
def create_pilot_status(
    student_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PilotStatusOut:
    student = _owned_student(db, student_id=student_id, user=user)
    try:
        enrollment = create_pilot_enrollment(db, student_id=student.id)
        db.commit()
        db.refresh(enrollment)
    except ValueError as error:
        db.rollback()
        if not _is_active_pilot_service_conflict(error):
            raise
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Student already has an active pilot enrollment",
        ) from error
    except IntegrityError as error:
        if not _is_active_pilot_integrity_conflict(error):
            raise
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Student already has an active pilot enrollment",
        ) from error
    return _pilot_status(db, enrollment)


@router.get("/{student_id}/pilot", response_model=PilotStatusOut)
def get_pilot_status(
    student_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PilotStatusOut:
    _owned_student(db, student_id=student_id, user=user)
    enrollment = _current_or_latest_pilot(db, student_id=student_id)
    if enrollment is None:
        raise HTTPException(status_code=404, detail="Pilot enrollment not found")
    return _pilot_status(db, enrollment)


def _assessment_error(
    db: Session,
    error: PilotAssessmentError,
) -> HTTPException:
    db.rollback()
    if isinstance(error, PilotAssessmentQuestionMismatch):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Assessment question is not current",
        )
    if isinstance(error, PilotAssessmentUnavailable):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pilot assessment is not available in the current phase",
        )
    if isinstance(error, (PilotAssessmentStateError, PilotAssessmentConfigurationError)):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Pilot assessment is temporarily unavailable",
        )
    if isinstance(error, PilotAssessmentNotFound):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pilot enrollment not found",
        )
    raise error


@router.get(
    "/{student_id}/pilot/assessment",
    response_model=PilotAssessmentItemOut,
)
def get_pilot_assessment(
    student_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PilotAssessmentItemOut:
    student = _owned_student(db, student_id=student_id, user=user)
    enrollment = _active_pilot(db, student_id=student.id)
    if enrollment is None:
        raise HTTPException(status_code=404, detail="Pilot enrollment not found")
    try:
        item = get_current_pilot_assessment_item(db, enrollment_id=enrollment.id)
    except (
        PilotAssessmentQuestionMismatch,
        PilotAssessmentUnavailable,
        PilotAssessmentStateError,
        PilotAssessmentConfigurationError,
        PilotAssessmentNotFound,
    ) as error:
        raise _assessment_error(db, error) from error
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pilot assessment is not available in the current phase",
        )
    return PilotAssessmentItemOut(**item.__dict__)


@router.post(
    "/{student_id}/pilot/assessment",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def submit_pilot_assessment(
    student_id: int,
    payload: PilotAssessmentSubmissionIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    student = _owned_student(db, student_id=student_id, user=user)
    enrollment = _active_pilot(db, student_id=student.id)
    if enrollment is None:
        raise HTTPException(status_code=404, detail="Pilot enrollment not found")
    try:
        submit_pilot_assessment_response(
            db,
            enrollment_id=enrollment.id,
            question_id=payload.question_id,
            candidate=payload.candidate,
            now=datetime.now(UTC).replace(tzinfo=None),
        )
        db.commit()
    except (
        PilotAssessmentQuestionMismatch,
        PilotAssessmentUnavailable,
        PilotAssessmentStateError,
        PilotAssessmentConfigurationError,
        PilotAssessmentNotFound,
    ) as error:
        raise _assessment_error(db, error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)

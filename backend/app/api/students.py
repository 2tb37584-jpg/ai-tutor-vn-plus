from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User, Student, Mastery
from app.models.entities import PilotEnrollment, PilotSkillAssignment
from app.schemas.student import StudentCreate, StudentOut, MasteryOut
from app.schemas.pilot import PilotStatusOut
from app.services.pilot_enrollment import create_pilot_enrollment

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

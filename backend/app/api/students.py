from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User, Student, Mastery
from app.schemas.student import StudentCreate, StudentOut, MasteryOut

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

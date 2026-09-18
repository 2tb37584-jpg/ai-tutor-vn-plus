from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User, Student, TutorSession, TutorMessage, Attempt
from app.schemas.tutor import (
    StartTutorRequest,
    StartTutorResponse,
    TutorReplyRequest,
    TutorReplyResponse,
    AttemptRequest,
)
from app.services.mastery import record_attempt
from app.services.tutor_ai import TutorAI

router = APIRouter(prefix="/tutor", tags=["tutor"])
ai = TutorAI()


def owned_student(db: Session, user: User, student_id: int) -> Student:
    student = db.get(Student, student_id)
    if student is None or student.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Student not found")
    return student


def owned_session(db: Session, user: User, session_id: int) -> TutorSession:
    session = db.get(TutorSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    owned_student(db, user, session.student_id)
    return session


@router.post("/start", response_model=StartTutorResponse)
def start_tutor(payload: StartTutorRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    student = owned_student(db, user, payload.student_id)
    if not payload.problem_text.strip() and not payload.image_data_url:
        raise HTTPException(status_code=422, detail="Provide problem_text or image_data_url")
    if payload.image_data_url and len(payload.image_data_url) > 8_000_000:
        raise HTTPException(status_code=413, detail="Image payload too large")

    analysis = ai.analyze_problem(payload.problem_text, payload.image_data_url)
    primary_skill = analysis.skills[0] if analysis.skills else "general.problem_solving"
    session = TutorSession(
        student_id=student.id,
        title=analysis.normalized_problem[:220] or "Tutoring session",
        normalized_problem=analysis.normalized_problem,
        primary_skill=primary_skill,
    )
    db.add(session)
    db.flush()

    tutor_turn = ai.first_turn(analysis, student.grade)
    db.add(TutorMessage(session_id=session.id, role="assistant", content=tutor_turn.message))
    db.commit()
    return StartTutorResponse(session_id=session.id, analysis=analysis, tutor=tutor_turn)


@router.post("/reply", response_model=TutorReplyResponse)
def tutor_reply(payload: TutorReplyRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    session = owned_session(db, user, payload.session_id)
    previous = list(
        db.scalars(
            select(TutorMessage)
            .where(TutorMessage.session_id == session.id)
            .order_by(TutorMessage.id)
        )
    )
    history = [(m.role, m.content) for m in previous]
    db.add(TutorMessage(session_id=session.id, role="user", content=payload.student_message))
    tutor_turn = ai.continue_turn(
        problem=session.normalized_problem,
        skill=session.primary_skill,
        history=history,
        student_message=payload.student_message,
    )
    db.add(TutorMessage(session_id=session.id, role="assistant", content=tutor_turn.message))
    db.commit()
    return TutorReplyResponse(tutor=tutor_turn)


@router.post("/attempt")
def save_attempt(payload: AttemptRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    owned_student(db, user, payload.student_id)
    if payload.session_id is not None:
        owned_session(db, user, payload.session_id)
    attempt = Attempt(**payload.model_dump())
    db.add(attempt)
    update = record_attempt(
        db,
        student_id=payload.student_id,
        skill_code=payload.skill_code,
        correct=payload.correct,
        hint_count=payload.hint_count,
    )
    db.commit()
    return {"ok": True, "mastery_before": update.old, "mastery_after": update.new}

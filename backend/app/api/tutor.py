from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User, Student, TutorSession, TutorMessage, Attempt
from app.schemas.tutor import (
    StartTutorRequest,
    StartTutorResponse,
    StudentProblemAnalysis,
    TutorReplyRequest,
    TutorReplyResponse,
    AttemptRequest,
    TutorState,
    TutorTurn,
)
from app.services.answer_leakage import detects_final_answer_leak
from app.services.mastery import record_attempt
from app.services.tutor_ai import TutorAI

router = APIRouter(prefix="/tutor", tags=["tutor"])
ai = TutorAI()
_SAFE_TUTOR_FALLBACK = "Em hãy tiếp tục từ bước em đang làm và giải thích vì sao bước đó hợp lý. Thầy/cô sẽ giúp em kiểm tra."


def _guard_tutor_turn(turn: TutorTurn, expected_answer: str) -> TutorTurn:
    if turn.state is TutorState.COMPLETE:
        return turn
    if not detects_final_answer_leak(turn.message, expected_answer, turn.reveal_final_answer):
        return turn
    return turn.model_copy(update={"message": _SAFE_TUTOR_FALLBACK, "reveal_final_answer": False})


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
        internal_expected_answer=analysis.expected_answer,
    )
    db.add(session)
    db.flush()

    tutor_turn = ai.first_turn(analysis, student.grade)
    tutor_turn = _guard_tutor_turn(tutor_turn, analysis.expected_answer)
    session.current_state = tutor_turn.state.value
    db.add(TutorMessage(session_id=session.id, role="assistant", content=tutor_turn.message))
    db.commit()
    public_analysis = StudentProblemAnalysis(
        normalized_problem=analysis.normalized_problem,
        subject=analysis.subject,
        grade_band=analysis.grade_band,
        skills=analysis.skills,
        prerequisites=analysis.prerequisites,
        confidence=analysis.confidence,
    )
    return StartTutorResponse(session_id=session.id, analysis=public_analysis, tutor=tutor_turn)


@router.post("/reply", response_model=TutorReplyResponse)
def tutor_reply(payload: TutorReplyRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    session = owned_session(db, user, payload.session_id)
    try:
        current_state = TutorState(session.current_state)
    except ValueError as error:
        raise HTTPException(status_code=500, detail="Tutor session is unavailable") from error

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
        current_state=current_state,
    )
    tutor_turn = _guard_tutor_turn(tutor_turn, session.internal_expected_answer)
    session.current_state = tutor_turn.state.value
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

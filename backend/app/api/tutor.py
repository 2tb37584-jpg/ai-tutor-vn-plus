import logging
from datetime import UTC, datetime

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
    TutorReplyIntent,
    TutorReplyResponse,
    TutorSessionSummaryResponse,
    AttemptRequest,
    AttemptResponse,
    TutorState,
    TutorTransitionEvent,
    TutorTransitionInput,
    TutorTurn,
)
from app.services.answer_leakage import detects_final_answer_leak
from app.services.mastery import (
    MasteryEvidenceEvent,
    MasteryEvidenceType,
    MasteryOutcome,
    VerificationStatus as MasteryVerificationStatus,
    record_mastery_evidence,
)
from app.services.question_bank import (
    get_question,
    get_transfer_question_for_skill,
    verification_request_for_candidate,
)
from app.services.session_summary import InvalidTutorSessionState, summarize_tutor_session
from app.services.skill_registry import get_controlled_skills
from app.services.tutor_ai import TutorAI
from app.services.tutor_state import InvalidTutorTransition, transition_tutor_state
from app.services.verification_policy import (
    EffectiveCorrectness,
    EscalationAction,
    resolve_verification_decision,
)
from app.services.verifier import (
    ExpressionEquivalenceRequest,
    LinearEquationRequest,
    NumericVerificationRequest,
    ProblemFamily,
    VerificationRequest,
    VerificationStatus,
    verify,
)

router = APIRouter(prefix="/tutor", tags=["tutor"])
ai = TutorAI()
logger = logging.getLogger(__name__)
_SAFE_TUTOR_FALLBACK = "Em hãy tiếp tục từ bước em đang làm và giải thích vì sao bước đó hợp lý. Thầy/cô sẽ giúp em kiểm tra."
_TUTOR_RUNTIME_VERIFICATION_FAMILIES = {
    ProblemFamily.NUMERIC,
    ProblemFamily.EXPRESSION_EQUIVALENCE,
    ProblemFamily.LINEAR_EQUATION,
}


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _guard_tutor_turn(turn: TutorTurn, expected_answer: str) -> TutorTurn:
    if turn.state is TutorState.COMPLETE:
        return turn
    if not detects_final_answer_leak(turn.message, expected_answer, turn.reveal_final_answer):
        return turn
    return turn.model_copy(update={"message": _SAFE_TUTOR_FALLBACK, "reveal_final_answer": False})


def _verification_family_for_primary_skill(primary_skill: str) -> str | None:
    for skill in get_controlled_skills():
        if skill.code != primary_skill:
            continue
        try:
            family = ProblemFamily(skill.verifier_family)
        except ValueError:
            return None
        if family not in _TUTOR_RUNTIME_VERIFICATION_FAMILIES:
            return None
        return family.value
    return None


def _verification_request_for_session(
    session: TutorSession,
    candidate: str,
) -> VerificationRequest | None:
    try:
        family = ProblemFamily(session.verification_family)
    except (TypeError, ValueError):
        return None

    if family is ProblemFamily.NUMERIC:
        return NumericVerificationRequest(
            family=family,
            expected=session.internal_expected_answer,
            candidate=candidate,
        )
    if family is ProblemFamily.EXPRESSION_EQUIVALENCE:
        return ExpressionEquivalenceRequest(
            family=family,
            left=session.internal_expected_answer,
            right=candidate,
        )
    if family is ProblemFamily.LINEAR_EQUATION:
        return LinearEquationRequest(
            family=family,
            equation=session.normalized_problem,
            candidate=candidate,
        )
    return None


def _transfer_verification_request_for_session(
    session: TutorSession,
    candidate: str,
) -> VerificationRequest | None:
    transfer_question_id = session.transfer_question_id
    if transfer_question_id is None:
        return None

    item = get_question(transfer_question_id)
    if item is None:
        return None
    if session.primary_skill and item.skill_code != session.primary_skill:
        return None

    try:
        return verification_request_for_candidate(item, candidate)
    except ValueError:
        return None


def _persist_transfer_question_id_on_entry(
    session: TutorSession,
    previous_state: TutorState,
    next_state: TutorState,
) -> None:
    if previous_state is TutorState.TRANSFER or next_state is not TutorState.TRANSFER:
        return
    if session.transfer_question_id is not None or not session.primary_skill:
        return

    item = get_transfer_question_for_skill(session.primary_skill)
    if item is not None:
        session.transfer_question_id = item.id


def _authoritative_state_for_correctness(
    current_state: TutorState,
    correctness: EffectiveCorrectness,
) -> TutorState:
    if correctness is EffectiveCorrectness.UNKNOWN:
        return current_state

    correct_events = {
        TutorState.ASK_ATTEMPT: TutorTransitionEvent.ATTEMPT_CORRECT,
        TutorState.HINT_1: TutorTransitionEvent.ATTEMPT_CORRECT,
        TutorState.HINT_2: TutorTransitionEvent.ATTEMPT_CORRECT,
        TutorState.VERIFY: TutorTransitionEvent.VERIFIED,
    }
    incorrect_events = {
        TutorState.ASK_ATTEMPT: TutorTransitionEvent.ATTEMPT_INCORRECT,
        TutorState.HINT_1: TutorTransitionEvent.ATTEMPT_INCORRECT,
        TutorState.HINT_2: TutorTransitionEvent.ATTEMPT_INCORRECT,
        TutorState.VERIFY: TutorTransitionEvent.VERIFICATION_FAILED,
    }
    event = (
        correct_events.get(current_state)
        if correctness is EffectiveCorrectness.CORRECT
        else incorrect_events.get(current_state)
    )
    if event is None:
        return current_state
    return transition_tutor_state(TutorTransitionInput(state=current_state, event=event))


def _turn_with_authoritative_state(turn: TutorTurn, state: TutorState) -> TutorTurn:
    hint_level = 1 if state is TutorState.HINT_1 else 2 if state is TutorState.HINT_2 else 0
    return turn.model_copy(update={"state": state, "hint_level": hint_level})


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
        verification_family=_verification_family_for_primary_skill(primary_skill),
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
    received_at = _utcnow()
    session = owned_session(db, user, payload.session_id)
    try:
        current_state = TutorState(session.current_state)
    except ValueError as error:
        raise HTTPException(status_code=500, detail="Tutor session is unavailable") from error

    if payload.intent is TutorReplyIntent.HINT_REQUEST:
        try:
            transition_tutor_state(
                TutorTransitionInput(
                    state=current_state,
                    event=TutorTransitionEvent.HINT_REQUESTED,
                )
            )
        except InvalidTutorTransition as error:
            raise HTTPException(
                status_code=409,
                detail="Hint request is unavailable in the current tutor state",
            ) from error

    previous = list(
        db.scalars(
            select(TutorMessage)
            .where(TutorMessage.session_id == session.id)
            .order_by(TutorMessage.id)
        )
    )
    history = [(m.role, m.content) for m in previous]
    previous_assistant = next(
        (message for message in reversed(previous) if message.role == "assistant"),
        None,
    )
    response_latency_ms = None
    if previous_assistant is not None and previous_assistant.created_at is not None:
        elapsed_ms = int(
            (received_at - previous_assistant.created_at).total_seconds() * 1000
        )
        response_latency_ms = max(0, elapsed_ms)
    db.add(
        TutorMessage(
            session_id=session.id,
            role="user",
            content=payload.student_message,
            reply_intent=payload.intent.value,
            response_latency_ms=response_latency_ms,
        )
    )
    turn_arguments = {
        "problem": session.normalized_problem,
        "skill": session.primary_skill,
        "history": history,
        "student_message": payload.student_message,
        "current_state": current_state,
    }
    if payload.intent is TutorReplyIntent.HINT_REQUEST:
        tutor_turn = ai.continue_turn(**turn_arguments, intent=payload.intent)
    else:
        tutor_turn = ai.continue_turn(**turn_arguments)

        if current_state is TutorState.TRANSFER:
            verification_request = _transfer_verification_request_for_session(
                session,
                payload.student_message,
            )
            next_state = TutorState.TRANSFER
            if (
                verification_request is not None
                and verify(verification_request).status is VerificationStatus.CORRECT
            ):
                next_state = transition_tutor_state(
                    TutorTransitionInput(
                        state=current_state,
                        event=TutorTransitionEvent.TRANSFER_COMPLETED,
                    )
                )
            tutor_turn = _turn_with_authoritative_state(tutor_turn, next_state)
        else:
            verification_request = _verification_request_for_session(
                session,
                payload.student_message,
            )
            if verification_request is not None:
                verification_result = verify(verification_request)
                retry_count = 0
                decision = resolve_verification_decision(
                    verification_result.status,
                    tutor_turn.likely_correct,
                )
                if decision.action is EscalationAction.RETRY_DETERMINISTIC:
                    retry_count = 1
                    verification_result = verify(verification_request)
                    decision = resolve_verification_decision(
                        verification_result.status,
                        tutor_turn.likely_correct,
                        retry_count=1,
                    )
                tutor_turn = _turn_with_authoritative_state(
                    tutor_turn,
                    _authoritative_state_for_correctness(
                        current_state,
                        decision.correctness,
                    ),
                )
                mastery_eligible = (
                    current_state
                    in {
                        TutorState.ASK_ATTEMPT,
                        TutorState.HINT_1,
                        TutorState.HINT_2,
                    }
                    and decision.correctness
                    in {EffectiveCorrectness.CORRECT, EffectiveCorrectness.INCORRECT}
                )
                logger.info(
                    "event=tutor_verification_decision session_id=%s skill_code=%s "
                    "problem_family=%s verifier_status=%s model_likely_correct=%s "
                    "disagreement=%s retry_count=%s escalation_outcome=%s "
                    "mastery_eligible=%s verification_method=%s",
                    session.id,
                    session.primary_skill,
                    verification_request.family.value,
                    verification_result.status.value,
                    str(tutor_turn.likely_correct).lower(),
                    str(decision.disagreement).lower(),
                    retry_count,
                    decision.action.value,
                    str(mastery_eligible).lower(),
                    session.verification_family,
                )
                if mastery_eligible:
                    record_mastery_evidence(
                        db,
                        MasteryEvidenceEvent(
                            student_id=session.student_id,
                            session_id=session.id,
                            skill_code=session.primary_skill,
                            outcome=(
                                MasteryOutcome.CORRECT
                                if decision.correctness is EffectiveCorrectness.CORRECT
                                else MasteryOutcome.INCORRECT
                            ),
                            evidence_type=MasteryEvidenceType.DETERMINISTIC_VERIFICATION,
                            verification_status=MasteryVerificationStatus.VERIFIED,
                            verification_method=session.verification_family,
                            confidence=1.0,
                            hint_count={
                                TutorState.ASK_ATTEMPT: 0,
                                TutorState.HINT_1: 1,
                                TutorState.HINT_2: 2,
                            }[current_state],
                            is_transfer=False,
                        ),
                    )
    tutor_turn = _guard_tutor_turn(tutor_turn, session.internal_expected_answer)
    _persist_transfer_question_id_on_entry(session, current_state, tutor_turn.state)
    session.current_state = tutor_turn.state.value
    db.add(TutorMessage(session_id=session.id, role="assistant", content=tutor_turn.message))
    db.commit()
    return TutorReplyResponse(tutor=tutor_turn)


@router.get(
    "/sessions/{session_id}/summary",
    response_model=TutorSessionSummaryResponse,
)
def tutor_session_summary(
    session_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TutorSessionSummaryResponse:
    session = owned_session(db, user, session_id)
    messages = list(
        db.scalars(
            select(TutorMessage)
            .where(TutorMessage.session_id == session.id)
            .order_by(TutorMessage.id)
        )
    )
    try:
        return summarize_tutor_session(session, messages)
    except InvalidTutorSessionState as error:
        raise HTTPException(
            status_code=500,
            detail="Tutor session is unavailable",
        ) from error


@router.post("/attempt", response_model=AttemptResponse)
def save_attempt(payload: AttemptRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    owned_student(db, user, payload.student_id)
    if payload.session_id is not None:
        owned_session(db, user, payload.session_id)
    attempt = Attempt(**payload.model_dump())
    db.add(attempt)
    db.commit()
    return AttemptResponse(
        mastery_updated=False,
        mastery_reason="client_claim_not_mastery_eligible",
    )

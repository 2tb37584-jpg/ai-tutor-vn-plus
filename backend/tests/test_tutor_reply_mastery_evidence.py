import pytest

from app.api import tutor as tutor_api
from app.models import Student, TutorMessage, TutorSession, User
from app.schemas.tutor import TutorReplyIntent, TutorReplyRequest, TutorState, TutorTurn
from app.services.mastery import (
    MasteryEvidenceEvent,
    MasteryEvidenceType,
    MasteryOutcome,
    VerificationStatus as MasteryVerificationStatus,
)
from app.services.verifier import VerificationResult, VerificationStatus


class FakeDatabase:
    def __init__(self, session: TutorSession) -> None:
        self.student = Student(id=session.student_id, owner_id=1, display_name="Student", grade=8)
        self.session = session
        self.messages = [TutorMessage(session_id=session.id, role="assistant", content="Start")]
        self.commits = 0

    def get(self, model: type[object], record_id: int) -> object | None:
        if model is Student and record_id == self.student.id:
            return self.student
        if model is TutorSession and record_id == self.session.id:
            return self.session
        return None

    def add(self, record: object) -> None:
        if isinstance(record, TutorMessage):
            self.messages.append(record)

    def commit(self) -> None:
        self.commits += 1

    def scalars(self, _statement: object) -> list[TutorMessage]:
        return self.messages.copy()


class FakeTutorAI:
    def __init__(self, turn: TutorTurn) -> None:
        self.turn = turn

    def continue_turn(
        self,
        problem: str,
        skill: str,
        history: list[tuple[str, str]],
        student_message: str,
        *,
        current_state: TutorState,
        intent: TutorReplyIntent | None = None,
    ) -> TutorTurn:
        return self.turn


def reply_context(
    *,
    current_state: TutorState = TutorState.ASK_ATTEMPT,
    verification_family: str | None = "numeric",
) -> tuple[User, TutorSession, FakeDatabase]:
    user = User(id=1, email="parent@example.com", password_hash="hash")
    session = TutorSession(
        id=2,
        student_id=1,
        normalized_problem="2 + 2",
        primary_skill="algebra.linear_equation",
        current_state=current_state.value,
        internal_expected_answer="4",
        verification_family=verification_family,
    )
    return user, session, FakeDatabase(session)


def reply(
    user: User,
    session: TutorSession,
    db: FakeDatabase,
    intent: TutorReplyIntent = TutorReplyIntent.ATTEMPT,
):
    return tutor_api.tutor_reply(
        TutorReplyRequest(session_id=session.id, student_message="4", intent=intent),
        user,
        db,
    )


@pytest.mark.parametrize(
    ("current_state", "status", "outcome", "hint_count"),
    [
        (TutorState.ASK_ATTEMPT, VerificationStatus.CORRECT, MasteryOutcome.CORRECT, 0),
        (TutorState.ASK_ATTEMPT, VerificationStatus.INCORRECT, MasteryOutcome.INCORRECT, 0),
        (TutorState.HINT_1, VerificationStatus.CORRECT, MasteryOutcome.CORRECT, 1),
        (TutorState.HINT_2, VerificationStatus.INCORRECT, MasteryOutcome.INCORRECT, 2),
    ],
)
def test_attempt_records_deterministic_mastery_evidence(
    monkeypatch: pytest.MonkeyPatch,
    current_state: TutorState,
    status: VerificationStatus,
    outcome: MasteryOutcome,
    hint_count: int,
) -> None:
    user, session, db = reply_context(current_state=current_state)
    events: list[MasteryEvidenceEvent] = []
    monkeypatch.setattr(
        tutor_api,
        "ai",
        FakeTutorAI(TutorTurn(message="Tutor response", state=TutorState.COMPLETE)),
    )
    monkeypatch.setattr(
        tutor_api,
        "verify",
        lambda _request: VerificationResult(status),
    )
    monkeypatch.setattr(tutor_api, "record_mastery_evidence", lambda _db, event: events.append(event))

    reply(user, session, db)

    assert events == [
        MasteryEvidenceEvent(
            student_id=session.student_id,
            session_id=session.id,
            skill_code=session.primary_skill,
            outcome=outcome,
            evidence_type=MasteryEvidenceType.DETERMINISTIC_VERIFICATION,
            verification_status=MasteryVerificationStatus.VERIFIED,
            verification_method=session.verification_family,
            confidence=1.0,
            hint_count=hint_count,
            is_transfer=False,
        )
    ]


@pytest.mark.parametrize(
    ("current_state", "verification_family", "statuses", "intent"),
    [
        (
            TutorState.ASK_ATTEMPT,
            "numeric",
            [VerificationStatus.UNSUPPORTED],
            TutorReplyIntent.ATTEMPT,
        ),
        (
            TutorState.ASK_ATTEMPT,
            "numeric",
            [VerificationStatus.INDETERMINATE, VerificationStatus.INDETERMINATE],
            TutorReplyIntent.ATTEMPT,
        ),
        (
            TutorState.ASK_ATTEMPT,
            "numeric",
            [],
            TutorReplyIntent.HINT_REQUEST,
        ),
        (TutorState.ASK_ATTEMPT, None, [], TutorReplyIntent.ATTEMPT),
        (TutorState.VERIFY, "numeric", [VerificationStatus.CORRECT], TutorReplyIntent.ATTEMPT),
        (TutorState.VERIFY, "numeric", [VerificationStatus.INCORRECT], TutorReplyIntent.ATTEMPT),
    ],
)
def test_ineligible_reply_paths_do_not_record_mastery_evidence(
    monkeypatch: pytest.MonkeyPatch,
    current_state: TutorState,
    verification_family: str | None,
    statuses: list[VerificationStatus],
    intent: TutorReplyIntent,
) -> None:
    user, session, db = reply_context(
        current_state=current_state,
        verification_family=verification_family,
    )
    events: list[MasteryEvidenceEvent] = []
    pending_statuses = iter(statuses)
    monkeypatch.setattr(
        tutor_api,
        "ai",
        FakeTutorAI(TutorTurn(message="Tutor response", state=TutorState.HINT_1)),
    )
    monkeypatch.setattr(
        tutor_api,
        "verify",
        lambda _request: VerificationResult(next(pending_statuses)),
    )
    monkeypatch.setattr(tutor_api, "record_mastery_evidence", lambda _db, event: events.append(event))

    reply(user, session, db, intent=intent)

    assert events == []

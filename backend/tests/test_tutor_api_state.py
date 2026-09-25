import pytest
import app.services.question_recommender as recommender
from fastapi import HTTPException

from app.api import tutor as tutor_api
from app.models import Student, TutorMessage, TutorSession, User
from app.schemas.tutor import (
    ProblemAnalysis,
    StartTutorRequest,
    TutorReplyRequest,
    TutorState,
    TutorTurn,
)
from app.services.mastery import MasteryEvidenceType, MasteryOutcome
import app.services.question_bank as question_bank
from app.services.question_bank import get_transfer_question_for_skill
from app.services.verifier import (
    FactorizationVerificationRequest,
    VerificationResult,
    VerificationStatus,
)


class FakeDatabase:
    def __init__(self, student: Student) -> None:
        self.student = student
        self.sessions: dict[int, TutorSession] = {}
        self.messages: list[TutorMessage] = []
        self.commits = 0

    def get(self, model: type[object], record_id: int) -> object | None:
        if model is Student:
            return self.student if record_id == self.student.id else None
        if model is TutorSession:
            return self.sessions.get(record_id)
        return None

    def add(self, record: object) -> None:
        if isinstance(record, TutorSession):
            record.id = len(self.sessions) + 1
            self.sessions[record.id] = record
        elif isinstance(record, TutorMessage):
            self.messages.append(record)

    def flush(self) -> None:
        pass

    def commit(self) -> None:
        self.commits += 1

    def scalars(self, _statement: object) -> list[TutorMessage]:
        return self.messages.copy()


class FakeTutorAI:
    def __init__(
        self,
        reply_states: list[TutorState],
        first_turn_state: TutorState = TutorState.ASK_ATTEMPT,
        analysis_skills: list[str] | None = None,
        reply_likely_correct: bool = False,
    ) -> None:
        self.reply_states = iter(reply_states)
        self.first_turn_state = first_turn_state
        self.analysis_skills = analysis_skills or ["algebra.linear_equation"]
        self.reply_likely_correct = reply_likely_correct
        self.received_states: list[TutorState] = []
        self.continue_calls = 0

    def analyze_problem(self, problem_text: str, image_data_url: str | None = None) -> ProblemAnalysis:
        return ProblemAnalysis(normalized_problem=problem_text, skills=self.analysis_skills)

    def first_turn(self, analysis: ProblemAnalysis, grade: int | None) -> TutorTurn:
        return TutorTurn(message="First question", state=self.first_turn_state)

    def continue_turn(
        self,
        problem: str,
        skill: str,
        history: list[tuple[str, str]],
        student_message: str,
        *,
        current_state: TutorState,
    ) -> TutorTurn:
        self.continue_calls += 1
        self.received_states.append(current_state)
        return TutorTurn(
            message="Next question",
            state=next(self.reply_states),
            likely_correct=self.reply_likely_correct,
        )


def tutor_context() -> tuple[User, Student, FakeDatabase]:
    user = User(id=1, email="parent@example.com", password_hash="hash")
    student = Student(id=1, owner_id=user.id, display_name="Student", grade=6)
    return user, student, FakeDatabase(student)


def start_session(user: User, db: FakeDatabase) -> int:
    response = tutor_api.start_tutor(
        StartTutorRequest(student_id=user.id, problem_text="Solve x + 1 = 2"),
        user=user,
        db=db,
    )
    return response.session_id


def test_start_persists_first_turn_state(monkeypatch: pytest.MonkeyPatch) -> None:
    user, _, db = tutor_context()
    fake_ai = FakeTutorAI([])
    monkeypatch.setattr(tutor_api, "ai", fake_ai)

    session_id = start_session(user, db)

    assert db.sessions[session_id].current_state == "ask_attempt"


def test_start_persists_state_returned_by_tutor_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    user, _, db = tutor_context()
    fake_ai = FakeTutorAI([], first_turn_state=TutorState.HINT_1)
    monkeypatch.setattr(tutor_api, "ai", fake_ai)

    session_id = start_session(user, db)

    assert db.sessions[session_id].current_state == "hint_1"


def test_replies_pass_and_persist_state_across_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    user, _, db = tutor_context()
    fake_ai = FakeTutorAI(
        [TutorState.HINT_1, TutorState.HINT_2],
        analysis_skills=["unknown.skill"],
    )
    monkeypatch.setattr(tutor_api, "ai", fake_ai)
    session_id = start_session(user, db)

    assert db.sessions[session_id].verification_family is None

    tutor_api.tutor_reply(TutorReplyRequest(session_id=session_id, student_message="x = 3"), user, db)
    assert db.sessions[session_id].current_state == "hint_1"

    tutor_api.tutor_reply(TutorReplyRequest(session_id=session_id, student_message="x = 4"), user, db)

    assert fake_ai.received_states == [TutorState.ASK_ATTEMPT, TutorState.HINT_1]
    assert db.sessions[session_id].current_state == "hint_2"


def test_invalid_persisted_state_fails_without_calling_tutor_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    user, _, db = tutor_context()
    fake_ai = FakeTutorAI([TutorState.HINT_1])
    monkeypatch.setattr(tutor_api, "ai", fake_ai)
    session_id = start_session(user, db)
    db.sessions[session_id].current_state = "not-a-state"

    with pytest.raises(HTTPException) as error:
        tutor_api.tutor_reply(TutorReplyRequest(session_id=session_id, student_message="Help"), user, db)

    assert error.value.status_code == 500
    assert fake_ai.continue_calls == 0


def test_entering_transfer_selects_and_reuses_exact_factorization_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, student, db = tutor_context()
    session = TutorSession(
        id=1,
        student_id=student.id,
        primary_skill="algebra.factorization",
        current_state=TutorState.VERIFY.value,
        internal_expected_answer="1",
        verification_family="numeric",
    )
    db.sessions[session.id] = session
    fake_ai = FakeTutorAI([TutorState.TRANSFER, TutorState.TRANSFER])
    monkeypatch.setattr(tutor_api, "ai", fake_ai)
    verification_statuses = iter(
        [VerificationStatus.CORRECT, VerificationStatus.INCORRECT]
    )
    evidence: list[object] = []
    monkeypatch.setattr(
        tutor_api,
        "verify",
        lambda _request: VerificationResult(next(verification_statuses)),
    )
    monkeypatch.setattr(
        tutor_api,
        "record_mastery_evidence",
        lambda _db, event: evidence.append(event),
    )
    monkeypatch.setattr(
        recommender,
        "recommend_next_question",
        lambda *args, **kwargs: pytest.fail(
            "transfer entry must not invoke the next-best-question recommender"
        ),
    )
    selected_skills: list[str] = []

    def select_once(skill_code: str):
        selected_skills.append(skill_code)
        return get_transfer_question_for_skill(skill_code)

    monkeypatch.setattr(tutor_api, "get_transfer_question_for_skill", select_once)

    tutor_api.tutor_reply(
        TutorReplyRequest(session_id=session.id, student_message="first"),
        user,
        db,
    )

    assert session.current_state == TutorState.TRANSFER.value
    assert session.transfer_question_id == "g8alg.factorization.001"
    assert selected_skills == ["algebra.factorization"]
    assert evidence == []

    tutor_api.tutor_reply(
        TutorReplyRequest(session_id=session.id, student_message="later"),
        user,
        db,
    )

    assert session.current_state == TutorState.TRANSFER.value
    assert session.transfer_question_id == "g8alg.factorization.001"
    assert selected_skills == ["algebra.factorization"]
    assert len(evidence) == 1
    assert evidence[0].is_transfer is True


@pytest.mark.parametrize(
    ("skill_code", "expected_id"),
    [
        ("algebra.rational_expression.domain", "g8alg.rational-expression-domain.001"),
        ("arithmetic.signed_number_operations", "g8alg.signed-number-operations.001"),
    ],
)
def test_transfer_question_selection_is_exact_and_declaration_ordered(
    skill_code: str,
    expected_id: str,
) -> None:
    item = get_transfer_question_for_skill(skill_code)

    assert item is not None
    assert item.id == expected_id
    assert item.skill_code == skill_code


def test_transfer_question_selection_excludes_non_mastery_supported_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    non_mastery_item = question_bank.QuestionBankItem(
        id="g8alg.non-mastery-numeric.001",
        skill_code="general.non_mastery_numeric",
        problem_text="non-mastery item",
        verification_reference="1",
        expected_answer="1",
        verification_family="numeric",
        difficulty=1,
    )
    monkeypatch.setattr(question_bank, "_QUESTION_BANK", (non_mastery_item,))

    assert get_transfer_question_for_skill("general.non_mastery_numeric") is None


@pytest.mark.parametrize(
    "skill_code",
    [None, "algebra.rational_expression.simplify", "algebra.factorization.neighbor"],
)
def test_transfer_question_selection_has_no_missing_or_related_skill_fallback(
    skill_code: str | None,
) -> None:
    session = TutorSession(
        student_id=1,
        primary_skill=skill_code,
        current_state=TutorState.VERIFY.value,
    )

    tutor_api._persist_transfer_question_id_on_entry(
        session,
        TutorState.VERIFY,
        TutorState.TRANSFER,
    )

    assert session.transfer_question_id is None


def test_transfer_question_selection_preserves_existing_id() -> None:
    session = TutorSession(
        student_id=1,
        primary_skill="algebra.factorization",
        transfer_question_id="g8alg.factorization.001",
        current_state=TutorState.VERIFY.value,
    )

    tutor_api._persist_transfer_question_id_on_entry(
        session,
        TutorState.VERIFY,
        TutorState.TRANSFER,
    )

    assert session.transfer_question_id == "g8alg.factorization.001"


def test_transfer_entry_does_not_complete_or_update_mastery() -> None:
    session = TutorSession(
        student_id=1,
        primary_skill="algebra.factorization",
        current_state=TutorState.VERIFY.value,
    )

    tutor_api._persist_transfer_question_id_on_entry(
        session,
        TutorState.VERIFY,
        TutorState.TRANSFER,
    )

    assert session.current_state == TutorState.VERIFY.value
    assert session.transfer_question_id == "g8alg.factorization.001"


def transfer_reply_context(
    monkeypatch: pytest.MonkeyPatch,
    *,
    likely_correct: bool,
) -> tuple[User, TutorSession, FakeDatabase]:
    user, student, db = tutor_context()
    session = TutorSession(
        id=1,
        student_id=student.id,
        primary_skill="algebra.factorization",
        transfer_question_id="g8alg.factorization.001",
        current_state=TutorState.TRANSFER.value,
        normalized_problem="original equation x + 100 = 200",
        internal_expected_answer="100",
        verification_family="numeric",
    )
    db.sessions[session.id] = session
    monkeypatch.setattr(
        tutor_api,
        "ai",
        FakeTutorAI([TutorState.COMPLETE], reply_likely_correct=likely_correct),
    )
    return user, session, db


@pytest.mark.parametrize(
    ("status", "likely_correct", "expected_state"),
    [
        (VerificationStatus.CORRECT, False, TutorState.COMPLETE),
        (VerificationStatus.INCORRECT, True, TutorState.TRANSFER),
        (VerificationStatus.UNSUPPORTED, True, TutorState.TRANSFER),
        (VerificationStatus.INDETERMINATE, True, TutorState.TRANSFER),
    ],
)
def test_transfer_deterministic_status_is_authoritative(
    monkeypatch: pytest.MonkeyPatch,
    status: VerificationStatus,
    likely_correct: bool,
    expected_state: TutorState,
) -> None:
    user, session, db = transfer_reply_context(
        monkeypatch,
        likely_correct=likely_correct,
    )
    evidence: list[object] = []
    monkeypatch.setattr(
        tutor_api,
        "verify",
        lambda _request: VerificationResult(status),
    )
    monkeypatch.setattr(
        tutor_api,
        "record_mastery_evidence",
        lambda _db, event: evidence.append(event),
    )

    response = tutor_api.tutor_reply(
        TutorReplyRequest(session_id=session.id, student_message="(x-3)*(x+3)"),
        user,
        db,
    )

    assert response.tutor.state is expected_state
    assert session.current_state == expected_state.value
    assert len(evidence) == (1 if status in {VerificationStatus.CORRECT, VerificationStatus.INCORRECT} else 0)
    if evidence:
        event = evidence[0]
        assert event.outcome is (
            MasteryOutcome.CORRECT
            if status is VerificationStatus.CORRECT
            else MasteryOutcome.INCORRECT
        )
        assert event.evidence_type is MasteryEvidenceType.DETERMINISTIC_VERIFICATION
        assert event.verification_status is tutor_api.MasteryVerificationStatus.VERIFIED
        assert event.verification_method == "factorization"
        assert event.student_id == session.student_id
        assert event.session_id == session.id
        assert event.confidence == 1.0
        assert event.hint_count == 0
        assert event.is_transfer is True
        assert event.skill_code == session.primary_skill


def test_transfer_missing_request_remains_transfer_without_original_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, session, db = transfer_reply_context(monkeypatch, likely_correct=True)
    session.transfer_question_id = None
    monkeypatch.setattr(
        tutor_api,
        "_verification_request_for_session",
        lambda *_args: pytest.fail("transfer must not use the original-session verifier"),
    )
    monkeypatch.setattr(
        tutor_api,
        "verify",
        lambda _request: pytest.fail("missing transfer request must not verify"),
    )
    monkeypatch.setattr(
        tutor_api,
        "record_mastery_evidence",
        lambda *_args, **_kwargs: pytest.fail("missing transfer request must not record evidence"),
    )

    response = tutor_api.tutor_reply(
        TutorReplyRequest(session_id=session.id, student_message="anything"),
        user,
        db,
    )

    assert response.tutor.state is TutorState.TRANSFER
    assert session.current_state == TutorState.TRANSFER.value


def test_transfer_uses_authored_context_without_duplicate_or_recommender_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, session, db = transfer_reply_context(monkeypatch, likely_correct=False)
    requests: list[object] = []
    evidence: list[object] = []
    transition_events: list[object] = []
    real_transition = tutor_api.transition_tutor_state
    monkeypatch.setattr(
        tutor_api,
        "verify",
        lambda request: requests.append(request)
        or VerificationResult(VerificationStatus.CORRECT),
    )
    monkeypatch.setattr(
        tutor_api,
        "record_mastery_evidence",
        lambda _db, event: evidence.append(event),
    )
    monkeypatch.setattr(
        recommender,
        "recommend_next_question",
        lambda *_args, **_kwargs: pytest.fail("transfer completion must not recommend"),
    )
    monkeypatch.setattr(
        tutor_api,
        "_verification_request_for_session",
        lambda *_args: pytest.fail("transfer must not use original-session context"),
    )
    monkeypatch.setattr(
        tutor_api,
        "transition_tutor_state",
        lambda transition: transition_events.append(transition.event)
        or real_transition(transition),
    )

    response = tutor_api.tutor_reply(
        TutorReplyRequest(session_id=session.id, student_message="(x-3)*(x+3)"),
        user,
        db,
    )

    assert response.tutor.state is TutorState.COMPLETE
    assert session.current_state == TutorState.COMPLETE.value
    assert transition_events == [tutor_api.TutorTransitionEvent.TRANSFER_COMPLETED]
    assert len(evidence) == 1
    assert evidence[0].is_transfer is True
    assert len(requests) == 1
    assert isinstance(requests[0], FactorizationVerificationRequest)
    assert requests[0].reference == "x^2-9"
    assert requests[0].candidate == "(x-3)*(x+3)"


def test_transfer_correct_without_primary_skill_skips_mastery_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, session, db = transfer_reply_context(monkeypatch, likely_correct=False)
    session.primary_skill = None
    monkeypatch.setattr(
        tutor_api,
        "verify",
        lambda _request: VerificationResult(VerificationStatus.CORRECT),
    )
    monkeypatch.setattr(
        tutor_api,
        "record_mastery_evidence",
        lambda *_args, **_kwargs: pytest.fail(
            "missing primary skill must not record transfer evidence"
        ),
    )

    response = tutor_api.tutor_reply(
        TutorReplyRequest(session_id=session.id, student_message="(x-3)*(x+3)"),
        user,
        db,
    )

    assert response.tutor.state is TutorState.COMPLETE
    assert session.current_state == TutorState.COMPLETE.value

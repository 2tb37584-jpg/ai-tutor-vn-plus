from datetime import datetime

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import deps, tutor as tutor_api
from app.db.session import Base
from app.main import app
from app.models import Student, TutorMessage, TutorSession, User
from app.models.entities import PilotEnrollment, PilotSkillAssignment
from app.schemas.tutor import (
    StartAuthoredTutorRequest,
    StartAuthoredTutorResponse,
    TutorState,
    TutorTurn,
)
from app.services import pilot_learning_start


_NOW = datetime(2026, 1, 1)
_ASSIGNMENTS = (
    ("arithmetic.signed_number_operations", "g8alg.signed-number-operations.001", "g8alg.signed-number-operations.002", "g8alg.signed-number-operations.003"),
    ("algebra.expression.distributive_property", "g8alg.distributive-property.001", "g8alg.distributive-property.002", "g8alg.distributive-property.003"),
    ("algebra.expression.combine_like_terms", "g8alg.combine-like-terms.001", "g8alg.combine-like-terms.002", "g8alg.combine-like-terms.003"),
    ("algebra.expression.simplify", "g8alg.expression-simplify.001", "g8alg.expression-simplify.002", "g8alg.expression-simplify.003"),
    ("algebra.identity.basic", "g8alg.identity-basic.001", "g8alg.identity-basic.002", "g8alg.identity-basic.003"),
    ("algebra.linear_equation", "g8alg.linear-equation.001", "g8alg.linear-equation.002", "g8alg.linear-equation.003"),
    ("algebra.equation.equivalent_transform", "g8alg.equivalent-transform.001", "g8alg.equivalent-transform.002", "g8alg.equivalent-transform.003"),
    ("algebra.factorization", "g8alg.factorization.001", "g8alg.factorization.002", "g8alg.factorization.003"),
    ("algebra.rational_expression.domain", "g8alg.rational-expression-domain.001", "g8alg.rational-expression-domain.002", "g8alg.rational-expression-domain.003"),
)


class FakeAI:
    def __init__(self, turn: TutorTurn | None = None) -> None:
        self.turn = turn or TutorTurn(
            message="Hãy bắt đầu từ bước đầu tiên.",
            state=TutorState.ASK_ATTEMPT,
        )
        self.calls = 0
        self.analysis = None

    def analyze_problem(self, *_args, **_kwargs):
        raise AssertionError("trusted authored start must not analyze model input")

    def first_turn(self, analysis, _grade):
        self.calls += 1
        self.analysis = analysis
        return self.turn


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        owner = User(id=1, email="owner@example.com", password_hash="hash")
        other_owner = User(id=2, email="other@example.com", password_hash="hash")
        session.add_all((owner, other_owner))
        session.flush()
        session.add_all(
            (
                Student(id=1, owner_id=owner.id, display_name="Owned", grade=8),
                Student(id=2, owner_id=other_owner.id, display_name="Other", grade=8),
            )
        )
        session.commit()
        yield session


def _add_pilot(
    db: Session,
    *,
    student_id: int = 1,
    phase: str = "intervention",
    completed_prefix: int = 0,
    assignment_count: int = 9,
) -> tuple[PilotEnrollment, list[PilotSkillAssignment]]:
    enrollment = PilotEnrollment(
        public_id=f"pilot-{student_id}-{phase}",
        student_id=student_id,
        phase=phase,
    )
    db.add(enrollment)
    db.flush()
    assignments: list[PilotSkillAssignment] = []
    for index, (skill, pre_id, learning_id, post_id) in enumerate(
        _ASSIGNMENTS[:assignment_count]
    ):
        assignment = PilotSkillAssignment(
            pilot_enrollment_id=enrollment.id,
            skill_code=skill,
            pre_question_id=pre_id,
            learning_question_id=learning_id,
            post_question_id=post_id,
            pre_verification_status="correct",
            pre_submitted_at=_NOW,
            learning_completed_at=_NOW if index < completed_prefix else None,
        )
        db.add(assignment)
        assignments.append(assignment)
    db.commit()
    return enrollment, assignments


def _start(db: Session):
    return tutor_api.start_pilot_learning_tutor(
        student_id=1,
        user=db.get(User, 1),
        db=db,
    )


def test_endpoint_has_no_request_body_and_reuses_safe_response_schema() -> None:
    route = next(
        route
        for route in tutor_api.router.routes
        if route.path == "/tutor/start-pilot-learning/{student_id}"
    )

    assert route.methods == {"POST"}
    assert route.response_model is StartAuthoredTutorResponse
    assert route.dependant.body_params == []


@pytest.mark.parametrize(("student_id", "user_id"), [(999, 1), (2, 1)])
def test_missing_and_non_owned_students_are_indistinguishable_and_checked_first(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    student_id: int,
    user_id: int,
) -> None:
    monkeypatch.setattr(
        tutor_api,
        "get_next_pilot_learning_start",
        lambda *_args, **_kwargs: pytest.fail("pilot lookup must follow ownership"),
    )

    with pytest.raises(HTTPException) as error:
        tutor_api.start_pilot_learning_tutor(
            student_id=student_id,
            user=db.get(User, user_id),
            db=db,
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Student not found"


def test_no_active_pilot_returns_non_disclosing_not_found(db: Session) -> None:
    with pytest.raises(HTTPException) as error:
        _start(db)

    assert error.value.status_code == 404
    assert error.value.detail == "Pilot enrollment not found"


@pytest.mark.parametrize("phase", ["pre", "post"])
def test_non_intervention_phase_returns_conflict(db: Session, phase: str) -> None:
    _add_pilot(db, phase=phase)

    with pytest.raises(HTTPException) as error:
        _start(db)

    assert error.value.status_code == 409
    assert error.value.detail == "Pilot learning is not available in the current phase"


def test_completed_only_pilot_returns_not_found(db: Session) -> None:
    _add_pilot(db, phase="complete")

    with pytest.raises(HTTPException) as error:
        _start(db)

    assert error.value.status_code == 404
    assert error.value.detail == "Pilot enrollment not found"


def test_valid_start_persists_exact_assignment_provenance_and_safe_response(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enrollment, assignments = _add_pilot(db, completed_prefix=3)
    ai = FakeAI()
    monkeypatch.setattr(tutor_api, "ai", ai)
    monkeypatch.setattr(
        tutor_api,
        "record_mastery_evidence",
        lambda *_args, **_kwargs: pytest.fail("start must not update mastery"),
    )

    response = _start(db)

    selected = assignments[3]
    session = db.get(TutorSession, response.session_id)
    assert session is not None
    assert session.student_id == 1
    assert session.authored_question_id == selected.learning_question_id
    assert session.pilot_skill_assignment_id == selected.id
    assert session.primary_skill == selected.skill_code
    assert session.transfer_question_id is None
    assert enrollment.phase == "intervention"
    assert [row.learning_completed_at for row in assignments] == [
        _NOW if index < 3 else None for index in range(9)
    ]
    assert ai.calls == 1
    assert ai.analysis.normalized_problem == response.question.problem_text

    payload = response.model_dump(mode="json")
    assert set(payload) == {"session_id", "question", "tutor"}
    assert set(payload["question"]) == {
        "question_id",
        "skill_code",
        "problem_text",
        "difficulty",
    }
    serialized = str(payload)
    for hidden in (
        "expected_answer",
        "verification_reference",
        "verification_family",
        "pilot_skill_assignment_id",
        "pilot_enrollment_id",
        assignments[3].pre_question_id,
        assignments[3].post_question_id,
        assignments[4].learning_question_id,
    ):
        assert hidden not in serialized


def test_generic_guard_rejects_frozen_learning_but_pilot_path_starts_it(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, assignments = _add_pilot(db)
    ai = FakeAI()
    monkeypatch.setattr(tutor_api, "ai", ai)

    with pytest.raises(HTTPException) as error:
        tutor_api.start_authored_tutor(
            StartAuthoredTutorRequest(
                student_id=1,
                question_id=assignments[0].learning_question_id,
            ),
            user=db.get(User, 1),
            db=db,
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Question not found"
    assert ai.calls == 0
    response = _start(db)
    assert response.question.question_id == assignments[0].learning_question_id
    assert ai.calls == 1


def test_server_selected_question_cannot_be_overridden_by_request_body(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, assignments = _add_pilot(db)
    monkeypatch.setattr(tutor_api, "ai", FakeAI())

    route = next(
        route
        for route in tutor_api.router.routes
        if route.path == "/tutor/start-pilot-learning/{student_id}"
    )
    assert route.dependant.body_params == []

    owner = db.get(User, 1)
    assert owner is not None
    app.dependency_overrides[deps.get_db] = lambda: db
    app.dependency_overrides[deps.get_current_user] = lambda: owner
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/tutor/start-pilot-learning/1",
                json={
                    "question_id": assignments[1].learning_question_id,
                    "pilot_skill_assignment_id": assignments[1].id,
                    "skill_code": assignments[1].skill_code,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["question"]["question_id"] == assignments[0].learning_question_id
    assert body["question"]["question_id"] != assignments[1].learning_question_id

    session = db.get(TutorSession, body["session_id"])
    assert session is not None
    assert session.authored_question_id == assignments[0].learning_question_id
    assert session.pilot_skill_assignment_id == assignments[0].id
    assert session.primary_skill == assignments[0].skill_code
    assert session.authored_question_id != assignments[1].learning_question_id
    assert session.pilot_skill_assignment_id != assignments[1].id
    assert session.primary_skill != assignments[1].skill_code


@pytest.mark.parametrize("failure", ["state", "configuration"])
def test_trusted_state_and_configuration_failures_map_to_generic_503_without_side_effects(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    _, assignments = _add_pilot(db, assignment_count=8 if failure == "state" else 9)
    if failure == "configuration":
        assignments[0].learning_question_id = "missing.learning.question"
        db.commit()
    ai = FakeAI()
    monkeypatch.setattr(tutor_api, "ai", ai)

    with pytest.raises(HTTPException) as error:
        _start(db)

    assert error.value.status_code == 503
    assert error.value.detail == "Pilot learning is temporarily unavailable"
    assert ai.calls == 0
    assert db.query(TutorSession).count() == 0
    assert db.query(TutorMessage).count() == 0


def test_unexpected_and_future_base_errors_propagate(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FuturePilotLearningError(pilot_learning_start.PilotLearningStartError):
        pass

    for raised in (RuntimeError("unexpected"), FuturePilotLearningError("future")):
        monkeypatch.setattr(
            tutor_api,
            "get_next_pilot_learning_start",
            lambda *_args, raised=raised, **_kwargs: (_ for _ in ()).throw(raised),
        )
        with pytest.raises(type(raised), match=str(raised)):
            _start(db)


@pytest.mark.parametrize(
    ("raised", "status_code", "detail"),
    [
        (
            pilot_learning_start.PilotLearningStartNotFound("missing"),
            404,
            "Pilot enrollment not found",
        ),
        (
            pilot_learning_start.PilotLearningStartUnavailable("phase"),
            409,
            "Pilot learning is not available in the current phase",
        ),
        (
            pilot_learning_start.PilotLearningStartStateError("state"),
            503,
            "Pilot learning is temporarily unavailable",
        ),
        (
            pilot_learning_start.PilotLearningStartConfigurationError("config"),
            503,
            "Pilot learning is temporarily unavailable",
        ),
    ],
)
def test_known_errors_map_without_session_message_or_ai_side_effects(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    raised: Exception,
    status_code: int,
    detail: str,
) -> None:
    ai = FakeAI()
    monkeypatch.setattr(tutor_api, "ai", ai)
    monkeypatch.setattr(
        tutor_api,
        "get_next_pilot_learning_start",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(raised),
    )

    with pytest.raises(HTTPException) as error:
        _start(db)

    assert error.value.status_code == status_code
    assert error.value.detail == detail
    assert ai.calls == 0
    assert db.query(TutorSession).count() == 0
    assert db.query(TutorMessage).count() == 0


def test_answer_leakage_guard_applies_to_pilot_first_turn(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _add_pilot(db)
    item = tutor_api.get_question("g8alg.signed-number-operations.002")
    assert item is not None
    monkeypatch.setattr(
        tutor_api,
        "ai",
        FakeAI(
            TutorTurn(
                message=item.expected_answer,
                state=TutorState.ASK_ATTEMPT,
                reveal_final_answer=False,
            )
        ),
    )

    response = _start(db)

    assert response.tutor.message == tutor_api._SAFE_TUTOR_FALLBACK
    message = db.query(TutorMessage).one()
    assert message.content == tutor_api._SAFE_TUTOR_FALLBACK


def test_repeated_start_keeps_same_incomplete_assignment_provenance(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, assignments = _add_pilot(db, completed_prefix=2)
    monkeypatch.setattr(tutor_api, "ai", FakeAI())

    first = _start(db)
    second = _start(db)
    sessions = db.query(TutorSession).order_by(TutorSession.id).all()

    assert first.session_id != second.session_id
    assert len(sessions) == 2
    assert {session.pilot_skill_assignment_id for session in sessions} == {
        assignments[2].id
    }
    assert {session.authored_question_id for session in sessions} == {
        assignments[2].learning_question_id
    }
    assert assignments[2].learning_completed_at is None


def test_non_pilot_generic_authored_start_remains_unchanged(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tutor_api, "ai", FakeAI())

    response = tutor_api.start_authored_tutor(
        StartAuthoredTutorRequest(
            student_id=1,
            question_id="g8alg.factorization.001",
        ),
        user=db.get(User, 1),
        db=db,
    )
    session = db.get(TutorSession, response.session_id)

    assert response.question.question_id == "g8alg.factorization.001"
    assert session is not None
    assert session.pilot_skill_assignment_id is None

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import deps, students as students_api
from app.db.session import Base
from app.main import app
from app.models.entities import (
    Attempt,
    Mastery,
    PilotEnrollment,
    PilotSkillAssignment,
    Student,
    TutorMessage,
    TutorSession,
    User,
)
from app.services import pilot_assessment
from app.services.verifier import VerificationResult, VerificationStatus


@pytest.fixture
def api_context():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    owner = User(email="assessment-owner@example.com", password_hash="hash")
    other = User(email="assessment-other@example.com", password_hash="hash")
    db.add_all([owner, other])
    db.flush()
    student = Student(owner_id=owner.id, display_name="Synthetic A", grade=8)
    other_student = Student(owner_id=other.id, display_name="Synthetic B", grade=8)
    db.add_all([student, other_student])
    db.commit()
    app.dependency_overrides[deps.get_db] = lambda: db
    app.dependency_overrides[deps.get_current_user] = lambda: owner
    client = TestClient(app)
    yield client, db, owner, student, other_student
    app.dependency_overrides.clear()
    db.close()


def add_enrollment(
    db: Session,
    student_id: int,
    *,
    phase: str = "pre",
    public_id: str = "pilot-current",
) -> PilotEnrollment:
    enrollment = PilotEnrollment(public_id=public_id, student_id=student_id, phase=phase)
    db.add(enrollment)
    db.flush()
    db.add(
        PilotSkillAssignment(
            pilot_enrollment_id=enrollment.id,
            skill_code="algebra.factorization",
            pre_question_id="g8alg.factorization.001",
            learning_question_id="g8alg.factorization.002",
            post_question_id="g8alg.factorization.003",
        )
    )
    db.commit()
    return enrollment


def assignment_for(db: Session, enrollment: PilotEnrollment) -> PilotSkillAssignment:
    assignment = db.scalar(
        select(PilotSkillAssignment).where(
            PilotSkillAssignment.pilot_enrollment_id == enrollment.id
        )
    )
    assert assignment is not None
    return assignment


def prepare_post(db: Session, enrollment: PilotEnrollment) -> None:
    assignment = assignment_for(db, enrollment)
    now = datetime(2026, 1, 1)
    assignment.pre_verification_status = "correct"
    assignment.pre_submitted_at = now
    assignment.learning_completed_at = now
    db.commit()


def test_owner_gets_current_pre_item_with_exact_safe_fields(api_context) -> None:
    client, db, _, student, _ = api_context
    enrollment = add_enrollment(db, student.id)

    response = client.get(f"/api/v1/students/{student.id}/pilot/assessment")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"phase", "question_id", "skill_code", "problem_text", "difficulty"}
    assert body["phase"] == "pre"
    assert body["question_id"] == "g8alg.factorization.001"
    assert body["skill_code"] == "algebra.factorization"
    serialized = str(body)
    for secret in (
        "expected_answer",
        "verification_reference",
        "verification_family",
        "verification_status",
        "learning_question_id",
        "g8alg.factorization.003",
    ):
        assert secret not in serialized


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize("student_id", [999, 2])
def test_missing_and_non_owned_students_are_indistinguishable(api_context, method, student_id):
    client, _, _, student, _ = api_context
    path = f"/api/v1/students/{student_id}/pilot/assessment"
    response = getattr(client, method)(path, json={"question_id": "x", "candidate": "y"}) if method == "post" else client.get(path)
    assert response.status_code == 404
    assert response.json() == {"detail": "Student not found"}
    assert student.id != student_id or response.json()["detail"] == "Student not found"


def test_unauthenticated_assessment_routes_are_rejected(api_context) -> None:
    client, _, _, student, _ = api_context
    app.dependency_overrides.pop(deps.get_current_user)
    assert client.get(f"/api/v1/students/{student.id}/pilot/assessment").status_code == 401
    assert client.post(
        f"/api/v1/students/{student.id}/pilot/assessment",
        json={"question_id": "x", "candidate": "y"},
    ).status_code == 401


def test_no_active_or_completed_only_enrollment_returns_404(api_context) -> None:
    client, db, _, student, _ = api_context
    completed = add_enrollment(db, student.id, phase="complete", public_id="pilot-complete")
    response = client.get(f"/api/v1/students/{student.id}/pilot/assessment")
    assert response.status_code == 404
    assert response.json() == {"detail": "Pilot enrollment not found"}
    assert completed.phase == "complete"


def test_active_enrollment_wins_over_older_completed_enrollment(api_context) -> None:
    client, db, _, student, _ = api_context
    add_enrollment(db, student.id, phase="complete", public_id="pilot-old")
    active = add_enrollment(db, student.id, public_id="pilot-active")

    response = client.get(f"/api/v1/students/{student.id}/pilot/assessment")

    assert response.status_code == 200
    assert response.json()["question_id"] == assignment_for(db, active).pre_question_id


def test_intervention_get_is_unavailable_without_learning_leakage(api_context) -> None:
    client, db, _, student, _ = api_context
    add_enrollment(db, student.id, phase="intervention")
    assignment = assignment_for(db, db.scalar(select(PilotEnrollment).where(PilotEnrollment.student_id == student.id)))
    assignment.pre_verification_status = "correct"
    assignment.pre_submitted_at = datetime(2026, 1, 1)
    db.commit()

    response = client.get(f"/api/v1/students/{student.id}/pilot/assessment")

    assert response.status_code == 409
    assert response.json() == {"detail": "Pilot assessment is not available in the current phase"}


def test_post_get_returns_only_current_post_item(api_context) -> None:
    client, db, _, student, _ = api_context
    enrollment = add_enrollment(db, student.id, phase="post")
    prepare_post(db, enrollment)

    response = client.get(f"/api/v1/students/{student.id}/pilot/assessment")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"phase", "question_id", "skill_code", "problem_text", "difficulty"}
    assert body["phase"] == "post"
    assert body["question_id"] == "g8alg.factorization.003"
    assert "g8alg.factorization.002" not in str(body)


@pytest.mark.parametrize(
    "question_id",
    [
        "g8alg.factorization.002",
        "g8alg.factorization.003",
        "g8alg.identity-basic.001",
        "not-authored",
    ],
)
def test_non_current_questions_return_generic_409_without_current_id(api_context, question_id):
    client, db, _, student, _ = api_context
    add_enrollment(db, student.id)
    response = client.post(
        f"/api/v1/students/{student.id}/pilot/assessment",
        json={"question_id": question_id, "candidate": "candidate"},
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "Assessment question is not current"}
    assert "g8alg.factorization.001" not in response.text


@pytest.mark.parametrize("verifier_status", list(VerificationStatus))
def test_all_normal_outcomes_return_identical_empty_204(api_context, monkeypatch, verifier_status):
    client, db, _, student, _ = api_context
    enrollment = add_enrollment(db, student.id)
    monkeypatch.setattr(
        pilot_assessment,
        "verify",
        lambda request: VerificationResult(verifier_status),
    )

    response = client.post(
        f"/api/v1/students/{student.id}/pilot/assessment",
        json={"question_id": "g8alg.factorization.001", "candidate": "synthetic candidate"},
    )

    assert response.status_code == 204
    assert response.content == b""
    assert response.headers.get("content-type") is None
    assignment = assignment_for(db, enrollment)
    assert assignment.pre_verification_status == verifier_status.value
    if verifier_status in {VerificationStatus.CORRECT, VerificationStatus.INCORRECT}:
        assert assignment.pre_submitted_at is not None
    else:
        assert assignment.pre_submitted_at is None


@pytest.mark.parametrize(
    "verifier_status",
    [VerificationStatus.CORRECT, VerificationStatus.INCORRECT],
)
def test_correct_and_incorrect_progress_without_public_feedback(
    api_context,
    monkeypatch,
    verifier_status,
):
    client, db, _, student, _ = api_context
    enrollment = add_enrollment(db, student.id)
    monkeypatch.setattr(pilot_assessment, "verify", lambda request: VerificationResult(verifier_status))
    response = client.post(
        f"/api/v1/students/{student.id}/pilot/assessment",
        json={"question_id": "g8alg.factorization.001", "candidate": "candidate"},
    )
    assert response.status_code == 204
    assert response.content == b""
    db.refresh(enrollment)
    assert enrollment.phase == "intervention"
    assert client.get(f"/api/v1/students/{student.id}/pilot/assessment").status_code == 409


def test_retryable_submission_commits_and_item_remains_current(api_context, monkeypatch):
    client, db, _, student, _ = api_context
    enrollment = add_enrollment(db, student.id)
    monkeypatch.setattr(pilot_assessment, "verify", lambda request: VerificationResult(VerificationStatus.UNSUPPORTED))
    response = client.post(
        f"/api/v1/students/{student.id}/pilot/assessment",
        json={"question_id": "g8alg.factorization.001", "candidate": "candidate"},
    )
    assert response.status_code == 204
    db.expire_all()
    assignment = assignment_for(db, enrollment)
    assert assignment.pre_verification_status == "unsupported"
    assert assignment.pre_submitted_at is None
    assert client.get(f"/api/v1/students/{student.id}/pilot/assessment").json()["question_id"] == "g8alg.factorization.001"


def test_submission_schema_rejects_client_authority_fields(api_context):
    client, _, _, student, _ = api_context
    response = client.post(
        f"/api/v1/students/{student.id}/pilot/assessment",
        json={"question_id": "x", "candidate": "y", "correct": True, "phase": "pre"},
    )
    assert response.status_code == 422


def test_submission_does_not_create_side_effect_records_or_echo_candidate(api_context, monkeypatch):
    client, db, _, student, _ = api_context
    add_enrollment(db, student.id)
    monkeypatch.setattr(pilot_assessment, "verify", lambda request: VerificationResult(VerificationStatus.CORRECT))
    candidate = "private synthetic candidate"
    response = client.post(
        f"/api/v1/students/{student.id}/pilot/assessment",
        json={"question_id": "g8alg.factorization.001", "candidate": candidate},
    )
    assert response.status_code == 204
    assert candidate not in response.text
    assert db.scalars(select(TutorMessage)).all() == []
    assert db.scalars(select(Attempt)).all() == []
    assert db.scalars(select(Mastery)).all() == []
    assert db.scalars(select(TutorSession)).all() == []


@pytest.mark.parametrize(
    ("exception", "status_code", "detail"),
    [
        (pilot_assessment.PilotAssessmentUnavailable("unavailable"), 409, "Pilot assessment is not available in the current phase"),
        (pilot_assessment.PilotAssessmentQuestionMismatch("mismatch"), 409, "Assessment question is not current"),
        (pilot_assessment.PilotAssessmentStateError("corrupt"), 503, "Pilot assessment is temporarily unavailable"),
        (pilot_assessment.PilotAssessmentConfigurationError("config"), 503, "Pilot assessment is temporarily unavailable"),
        (pilot_assessment.PilotAssessmentNotFound("internal id"), 404, "Pilot enrollment not found"),
    ],
)
def test_expected_assessment_errors_are_generic(
    api_context,
    monkeypatch,
    exception,
    status_code,
    detail,
):
    client, db, _, student, _ = api_context
    add_enrollment(db, student.id)
    monkeypatch.setattr(
        students_api,
        "submit_pilot_assessment_response",
        lambda _db, **kwargs: (_ for _ in ()).throw(exception),
    )
    response = client.post(
        f"/api/v1/students/{student.id}/pilot/assessment",
        json={"question_id": "g8alg.factorization.001", "candidate": "candidate"},
    )
    assert response.status_code == status_code
    assert response.json() == {"detail": detail}
    assert "internal" not in response.text
    assert "g8alg" not in response.text


def test_unexpected_assessment_exception_propagates(api_context, monkeypatch):
    client, db, _, student, _ = api_context
    add_enrollment(db, student.id)
    error = RuntimeError("unexpected assessment failure")
    monkeypatch.setattr(
        students_api,
        "submit_pilot_assessment_response",
        lambda _db, **kwargs: (_ for _ in ()).throw(error),
    )
    with pytest.raises(RuntimeError, match="unexpected assessment failure"):
        client.post(
            f"/api/v1/students/{student.id}/pilot/assessment",
            json={"question_id": "g8alg.factorization.001", "candidate": "candidate"},
        )


class SyntheticAssessmentDomainError(pilot_assessment.PilotAssessmentError):
    pass


def test_unknown_assessment_domain_exception_propagates(api_context, monkeypatch):
    client, db, _, student, _ = api_context
    add_enrollment(db, student.id)
    error = SyntheticAssessmentDomainError("synthetic unknown assessment failure")
    monkeypatch.setattr(
        students_api,
        "submit_pilot_assessment_response",
        lambda _db, **kwargs: (_ for _ in ()).throw(error),
    )
    with pytest.raises(SyntheticAssessmentDomainError, match="synthetic unknown"):
        client.post(
            f"/api/v1/students/{student.id}/pilot/assessment",
            json={"question_id": "g8alg.factorization.001", "candidate": "candidate"},
        )


def test_openapi_assessment_contract_is_narrow(api_context):
    client, _, _, _, _ = api_context
    schema = client.get("/openapi.json").json()
    path = schema["paths"]["/api/v1/students/{student_id}/pilot/assessment"]
    assert set(path) == {"get", "post"}
    assert set(path["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].split("/")[-1:]) == {"PilotAssessmentItemOut"}
    post_schema = path["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert post_schema.endswith("PilotAssessmentSubmissionIn")
    submission_schema = schema["components"]["schemas"]["PilotAssessmentSubmissionIn"]
    assert set(submission_schema["properties"]) == {"question_id", "candidate"}
    assert submission_schema["additionalProperties"] is False
    assert "204" in path["post"]["responses"]
    assert "content" not in path["post"]["responses"]["204"]

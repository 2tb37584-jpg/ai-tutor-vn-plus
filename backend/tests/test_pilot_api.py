from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import deps, students as students_api
from app.db.session import Base
from app.main import app
from app.models.entities import PilotEnrollment, PilotSkillAssignment, Student, User


@pytest.fixture
def api_context():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    owner = User(email="owner@example.com", password_hash="hash")
    other = User(email="other@example.com", password_hash="hash")
    db.add_all([owner, other])
    db.flush()
    owned = Student(owner_id=owner.id, display_name="Synthetic A", grade=8)
    other_student = Student(owner_id=other.id, display_name="Synthetic B", grade=8)
    db.add_all([owned, other_student])
    db.commit()

    app.dependency_overrides[deps.get_db] = lambda: db
    app.dependency_overrides[deps.get_current_user] = lambda: owner
    client = TestClient(app)
    yield client, db, owner, owned, other_student
    app.dependency_overrides.clear()
    db.close()


def test_owner_can_enroll_and_response_is_learner_safe(api_context) -> None:
    client, db, _, student, _ = api_context

    response = client.post(f"/api/v1/students/{student.id}/pilot")

    assert response.status_code == 201
    body = response.json()
    assert body["phase"] == "pre"
    assert body["pilot_id"]
    persisted_assignments = db.scalars(
        select(PilotSkillAssignment).join(PilotEnrollment)
    ).all()
    assert body["skills_total"] == len(persisted_assignments) == 9
    assert body["pre_completed_skills"] == 0
    assert body["learning_completed_skills"] == 0
    assert body["post_completed_skills"] == 0
    assert set(body) == {
        "pilot_id",
        "phase",
        "skills_total",
        "pre_completed_skills",
        "learning_completed_skills",
        "post_completed_skills",
    }
    serialized = str(body)
    for secret in ("assignment_seed", "pre_question_id", "learning_question_id", "post_question_id", "expected_answer", "verification_reference", "verification_family"):
        assert secret not in serialized
    assert db.scalar(select(PilotEnrollment).where(PilotEnrollment.student_id == student.id))


def test_status_counts_persisted_completion_timestamps(api_context) -> None:
    client, db, _, student, _ = api_context
    client.post(f"/api/v1/students/{student.id}/pilot")
    enrollment = db.scalar(select(PilotEnrollment).where(PilotEnrollment.student_id == student.id))
    assert enrollment is not None
    assignments = db.scalars(
        select(PilotSkillAssignment).where(
            PilotSkillAssignment.pilot_enrollment_id == enrollment.id
        )
    ).all()
    now = datetime(2026, 1, 1)
    assignments[0].pre_submitted_at = now
    assignments[1].learning_completed_at = now
    assignments[2].post_submitted_at = now
    db.commit()

    response = client.get(f"/api/v1/students/{student.id}/pilot")

    assert response.json()["pre_completed_skills"] == 1
    assert response.json()["learning_completed_skills"] == 1
    assert response.json()["post_completed_skills"] == 1


def test_status_prefers_active_over_completed_and_falls_back_to_latest_completed(api_context) -> None:
    client, db, _, student, _ = api_context
    old = PilotEnrollment(
        public_id="old",
        student_id=student.id,
        phase="complete",
        created_at=datetime(2026, 1, 1),
    )
    db.add(old)
    db.flush()
    db.add(PilotSkillAssignment(
        pilot_enrollment_id=old.id, skill_code="old", pre_question_id="a", learning_question_id="b", post_question_id="c"
    ))
    db.commit()
    active_response = client.post(f"/api/v1/students/{student.id}/pilot")
    assert active_response.status_code == 201
    assert active_response.json()["phase"] == "pre"

    active = db.scalar(select(PilotEnrollment).where(PilotEnrollment.student_id == student.id, PilotEnrollment.phase != "complete"))
    assert active is not None
    active.phase = "complete"
    active.created_at = datetime(2026, 2, 1)
    db.commit()
    latest = client.get(f"/api/v1/students/{student.id}/pilot")
    assert latest.status_code == 200
    assert latest.json()["pilot_id"] == active.public_id


@pytest.mark.parametrize("student_id", [999, 2])
def test_missing_or_non_owned_student_is_not_enumerated(api_context, student_id: int) -> None:
    client, _, _, _, _ = api_context
    response = client.post(f"/api/v1/students/{student_id}/pilot")
    assert response.status_code == 404
    assert response.json()["detail"] == "Student not found"


def test_no_enrollment_returns_404(api_context) -> None:
    client, _, _, student, _ = api_context
    response = client.get(f"/api/v1/students/{student.id}/pilot")
    assert response.status_code == 404
    assert response.json()["detail"] == "Pilot enrollment not found"


def test_duplicate_active_enrollment_returns_409(api_context) -> None:
    client, _, _, student, _ = api_context
    assert client.post(f"/api/v1/students/{student.id}/pilot").status_code == 201
    response = client.post(f"/api/v1/students/{student.id}/pilot")
    assert response.status_code == 409
    assert response.json()["detail"] == "Student already has an active pilot enrollment"


def test_completed_enrollment_allows_new_enrollment(api_context) -> None:
    client, db, _, student, _ = api_context
    assert client.post(f"/api/v1/students/{student.id}/pilot").status_code == 201
    enrollment = db.scalar(select(PilotEnrollment).where(PilotEnrollment.student_id == student.id))
    assert enrollment is not None
    enrollment.phase = "complete"
    db.commit()
    assert client.post(f"/api/v1/students/{student.id}/pilot").status_code == 201


def test_recognized_integrity_race_maps_to_409(api_context, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, _, student, _ = api_context
    error = IntegrityError("insert", {}, Exception("UNIQUE constraint failed: pilot_enrollments.student_id"))
    monkeypatch.setattr(students_api, "create_pilot_enrollment", lambda *args, **kwargs: (_ for _ in ()).throw(error))
    assert client.post(f"/api/v1/students/{student.id}/pilot").status_code == 409


def test_unrelated_integrity_error_is_not_hidden(api_context, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, _, student, _ = api_context
    error = IntegrityError("insert", {}, Exception("UNIQUE constraint failed: unrelated_table.key"))
    monkeypatch.setattr(students_api, "create_pilot_enrollment", lambda *args, **kwargs: (_ for _ in ()).throw(error))
    with pytest.raises(IntegrityError):
        client.post(f"/api/v1/students/{student.id}/pilot")


def test_routes_have_no_request_body_and_response_contract_is_minimal(api_context) -> None:
    client, _, _, _, _ = api_context
    schema = client.get("/openapi.json").json()
    post = schema["paths"]["/api/v1/students/{student_id}/pilot"]["post"]
    assert "requestBody" not in post
    response_fields = set(schema["components"]["schemas"]["PilotStatusOut"]["properties"])
    assert response_fields == {
        "pilot_id", "phase", "skills_total", "pre_completed_skills",
        "learning_completed_skills", "post_completed_skills",
    }


def test_unauthenticated_request_is_rejected(api_context) -> None:
    client, _, _, student, _ = api_context
    app.dependency_overrides.pop(deps.get_current_user)
    response = client.get(f"/api/v1/students/{student.id}/pilot")
    assert response.status_code == 401

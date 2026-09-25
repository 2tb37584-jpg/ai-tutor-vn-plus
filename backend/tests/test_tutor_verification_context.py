import pytest

from app.api import tutor as tutor_api
from app.models import Student, TutorMessage, TutorSession, User
from app.schemas.tutor import ProblemAnalysis, StartTutorRequest, StartTutorResponse, TutorState, TutorTurn
from app.services.question_bank import QuestionBankItem, get_question
from app.services.skill_registry import SkillDefinition
from app.services.verifier import (
    DomainConditionVerificationRequest,
    ExpressionEquivalenceRequest,
    FactorizationVerificationRequest,
    LinearEquationRequest,
    NumericVerificationRequest,
    ProblemFamily,
    VerificationStatus,
    verify,
)


class FakeDatabase:
    def __init__(self, student: Student) -> None:
        self.student = student
        self.session: TutorSession | None = None
        self.messages: list[TutorMessage] = []

    def get(self, model: type[object], record_id: int) -> object | None:
        if model is Student and record_id == self.student.id:
            return self.student
        return None

    def add(self, record: object) -> None:
        if isinstance(record, TutorSession):
            record.id = 1
            self.session = record
        elif isinstance(record, TutorMessage):
            self.messages.append(record)

    def flush(self) -> None:
        pass

    def commit(self) -> None:
        pass


class FakeTutorAI:
    def __init__(self, analysis: ProblemAnalysis) -> None:
        self.analysis = analysis

    def analyze_problem(self, problem_text: str, image_data_url: str | None = None) -> ProblemAnalysis:
        return self.analysis

    def first_turn(self, analysis: ProblemAnalysis, grade: int | None) -> TutorTurn:
        return TutorTurn(message="What would you try first?", state=TutorState.ASK_ATTEMPT)


def controlled_skill(code: str, verifier_family: str) -> SkillDefinition:
    return SkillDefinition(
        code=code,
        name_vi="Test skill",
        subject="math",
        grade_min=8,
        grade_max=8,
        prerequisites=(),
        aliases=(),
        observable_mastery_evidence=(),
        common_misconceptions=(),
        verifier_family=verifier_family,
    )


@pytest.mark.parametrize(
    ("skills", "registry_family", "registry_matches", "expected_family"),
    [
        (["skill.numeric"], "numeric", True, "numeric"),
        (["skill.expression"], "expression_equivalence", True, "expression_equivalence"),
        (["skill.linear"], "linear_equation", True, "linear_equation"),
        (["skill.factorization"], "factorization", True, None),
        (["skill.manual"], "manual_or_future", True, None),
        (["unknown.skill"], "numeric", False, None),
        ([], "numeric", False, None),
    ],
)
def test_start_persists_only_registry_backed_implemented_verifier_families(
    monkeypatch: pytest.MonkeyPatch,
    skills: list[str],
    registry_family: str,
    registry_matches: bool,
    expected_family: str | None,
) -> None:
    analysis = ProblemAnalysis(
        normalized_problem="Source text must not determine routing",
        skills=skills,
        expected_answer="3/2",
    )
    primary_skill = skills[0] if skills else "general.problem_solving"
    registry = (
        (controlled_skill(primary_skill, registry_family),)
        if registry_matches
        else ()
    )
    monkeypatch.setattr(tutor_api, "ai", FakeTutorAI(analysis))
    monkeypatch.setattr(tutor_api, "get_controlled_skills", lambda: registry)
    user = User(id=1, email="parent@example.com", password_hash="hash")
    student = Student(id=1, owner_id=1, display_name="Student", grade=8)
    db = FakeDatabase(student)

    response = tutor_api.start_tutor(
        StartTutorRequest(student_id=1, problem_text="Unrelated prose"),
        user=user,
        db=db,
    )
    serialized = StartTutorResponse.model_validate(response).model_dump(mode="json")

    assert db.session is not None
    assert db.session.primary_skill == primary_skill
    assert db.session.verification_family == expected_family
    assert "verification_family" not in serialized
    assert "verification_family" not in serialized["analysis"]


def test_registered_family_requires_explicit_tutor_runtime_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tutor_api,
        "_TUTOR_RUNTIME_VERIFICATION_FAMILIES",
        {
            ProblemFamily.EXPRESSION_EQUIVALENCE,
            ProblemFamily.LINEAR_EQUATION,
        },
    )
    monkeypatch.setattr(
        tutor_api,
        "get_controlled_skills",
        lambda: (controlled_skill("skill.numeric", "numeric"),),
    )

    assert (
        tutor_api._verification_family_for_primary_skill("skill.numeric")
        is None
    )


def transfer_session(question_id: str, primary_skill: str) -> TutorSession:
    return TutorSession(
        student_id=1,
        primary_skill=primary_skill,
        transfer_question_id=question_id,
        normalized_problem="original session problem",
        internal_expected_answer="original session answer",
        verification_family="manual_or_future",
    )


def authored_session(question_id: str, primary_skill: str) -> TutorSession:
    return TutorSession(
        student_id=1,
        primary_skill=primary_skill,
        authored_question_id=question_id,
        normalized_problem="misleading original session problem",
        internal_expected_answer="misleading original session answer",
        verification_family="numeric",
    )


@pytest.mark.parametrize(
    ("question_id", "request_type", "trusted_field", "candidate_field", "candidate"),
    [
        (
            "g8alg.factorization.001",
            FactorizationVerificationRequest,
            "reference",
            "candidate",
            "(x-3)*(x+3)",
        ),
        (
            "g8alg.rational-expression-domain.001",
            DomainConditionVerificationRequest,
            "reference",
            "candidate",
            "x != 2",
        ),
    ],
)
def test_authored_verification_uses_authored_reference_and_candidate(
    question_id: str,
    request_type: type[object],
    trusted_field: str,
    candidate_field: str,
    candidate: str,
) -> None:
    item = get_question(question_id)
    assert item is not None
    session = authored_session(item.id, item.skill_code)

    request = tutor_api._verification_request_for_session(session, candidate)

    assert isinstance(request, request_type)
    assert getattr(request, trusted_field) == item.verification_reference
    assert getattr(request, candidate_field) == candidate
    assert getattr(request, trusted_field) != session.internal_expected_answer
    assert verify(request).status is VerificationStatus.CORRECT


def test_authored_verification_unknown_id_fails_closed_without_generic_fallback() -> None:
    session = authored_session("g8alg.does-not-exist.999", "algebra.factorization")

    assert tutor_api._verification_request_for_session(session, "candidate") is None


def test_authored_verification_rejects_skill_mismatch() -> None:
    item = get_question("g8alg.factorization.001")
    assert item is not None
    session = authored_session(item.id, "arithmetic.signed_number_operations")

    assert tutor_api._verification_request_for_session(session, "candidate") is None


def test_authored_verification_expected_builder_value_error_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = get_question("g8alg.factorization.001")
    assert item is not None
    session = authored_session(item.id, item.skill_code)

    def raise_expected_error(item: QuestionBankItem, candidate: str) -> object:
        raise ValueError("unsupported authored context")

    monkeypatch.setattr(
        tutor_api,
        "verification_request_for_candidate",
        raise_expected_error,
    )

    assert tutor_api._verification_request_for_session(session, "candidate") is None


def test_authored_verification_propagates_unexpected_builder_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = get_question("g8alg.factorization.001")
    assert item is not None
    session = authored_session(item.id, item.skill_code)

    def raise_unexpected_error(item: QuestionBankItem, candidate: str) -> object:
        raise TypeError("unexpected authored builder failure")

    monkeypatch.setattr(
        tutor_api,
        "verification_request_for_candidate",
        raise_unexpected_error,
    )

    with pytest.raises(TypeError, match="unexpected authored builder failure"):
        tutor_api._verification_request_for_session(session, "candidate")


def test_free_form_numeric_verification_remains_available() -> None:
    session = TutorSession(
        student_id=1,
        primary_skill="algebra.linear_equation",
        normalized_problem="2 + 2",
        internal_expected_answer="4",
        verification_family="numeric",
    )

    request = tutor_api._verification_request_for_session(session, "4")

    assert isinstance(request, NumericVerificationRequest)
    assert request.expected == "4"
    assert request.candidate == "4"


def test_transfer_verification_requires_persisted_question_id() -> None:
    session = transfer_session(
        "g8alg.factorization.001",
        "algebra.factorization",
    )
    session.transfer_question_id = None

    assert tutor_api._transfer_verification_request_for_session(session, "(x-3)*(x+3)") is None


def test_transfer_verification_does_not_fallback_for_unknown_id() -> None:
    session = transfer_session(
        "g8alg.does-not-exist.999",
        "algebra.factorization",
    )

    assert tutor_api._transfer_verification_request_for_session(session, "(x-3)*(x+3)") is None


def test_transfer_verification_rejects_authored_skill_mismatch() -> None:
    session = transfer_session(
        "g8alg.factorization.001",
        "arithmetic.signed_number_operations",
    )

    assert tutor_api._transfer_verification_request_for_session(session, "(x-3)*(x+3)") is None


@pytest.mark.parametrize(
    ("question_id", "request_type", "trusted_field", "candidate_field", "candidate"),
    [
        (
            "g8alg.signed-number-operations.001",
            NumericVerificationRequest,
            "expected",
            "candidate",
            "5",
        ),
        (
            "g8alg.distributive-property.001",
            ExpressionEquivalenceRequest,
            "left",
            "right",
            "3*x-6",
        ),
        (
            "g8alg.linear-equation.001",
            LinearEquationRequest,
            "equation",
            "candidate",
            "7",
        ),
        (
            "g8alg.factorization.001",
            FactorizationVerificationRequest,
            "reference",
            "candidate",
            "(x-3)*(x+3)",
        ),
        (
            "g8alg.rational-expression-domain.001",
            DomainConditionVerificationRequest,
            "reference",
            "candidate",
            "x != 2",
        ),
    ],
)
def test_transfer_verification_uses_authored_reference_and_learner_candidate(
    question_id: str,
    request_type: type[object],
    trusted_field: str,
    candidate_field: str,
    candidate: str,
) -> None:
    item = get_question(question_id)
    assert item is not None
    session = transfer_session(question_id, item.skill_code)

    request = tutor_api._transfer_verification_request_for_session(session, candidate)

    assert isinstance(request, request_type)
    assert getattr(request, trusted_field) == item.verification_reference
    assert getattr(request, candidate_field) == candidate
    assert verify(request).status is VerificationStatus.CORRECT


def test_transfer_verification_ignores_original_session_verification_fields() -> None:
    item = get_question("g8alg.linear-equation.001")
    assert item is not None
    session = transfer_session(item.id, item.skill_code)

    request = tutor_api._transfer_verification_request_for_session(session, "7")

    assert isinstance(request, LinearEquationRequest)
    assert request.equation == item.verification_reference
    assert request.equation != session.normalized_problem
    assert request.candidate == "7"


def test_transfer_verification_does_not_support_manual_or_future(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = QuestionBankItem(
        id="manual.item.001",
        skill_code="algebra.factorization",
        problem_text="manual",
        verification_reference="reference",
        expected_answer="answer",
        verification_family="manual_or_future",
        difficulty=1,
    )
    monkeypatch.setattr(tutor_api, "get_question", lambda question_id: item)
    session = transfer_session(item.id, item.skill_code)

    assert tutor_api._transfer_verification_request_for_session(session, "candidate") is None


def test_transfer_verification_propagates_unexpected_builder_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = get_question("g8alg.factorization.001")
    assert item is not None
    session = transfer_session(item.id, item.skill_code)

    def raise_unexpected_error(item: QuestionBankItem, candidate: str) -> object:
        raise TypeError("unexpected builder failure")

    monkeypatch.setattr(
        tutor_api,
        "verification_request_for_candidate",
        raise_unexpected_error,
    )

    with pytest.raises(TypeError, match="unexpected builder failure"):
        tutor_api._transfer_verification_request_for_session(session, "candidate")

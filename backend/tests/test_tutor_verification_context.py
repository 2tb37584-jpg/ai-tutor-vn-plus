import pytest

from app.api import tutor as tutor_api
from app.models import Student, TutorMessage, TutorSession, User
from app.schemas.tutor import ProblemAnalysis, StartTutorRequest, StartTutorResponse, TutorState, TutorTurn
from app.services.skill_registry import SkillDefinition
from app.services.verifier import ProblemFamily


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

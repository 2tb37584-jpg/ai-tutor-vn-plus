from collections import Counter
from dataclasses import FrozenInstanceError, asdict, replace

import pytest
import app.services.question_bank as question_bank

from app.services.question_bank import (
    QuestionBankItem,
    _build_question_bank,
    _verification_request,
    get_all_questions,
    get_question,
    get_questions_for_skill,
)
from app.services.skill_registry import (
    get_controlled_skills,
    get_skill_definition,
    is_mastery_bearing_skill,
    resolve_skill_code,
)
from app.services.verifier import (
    DomainConditionVerificationRequest,
    ExpressionEquivalenceRequest,
    FactorizationVerificationRequest,
    LinearEquationRequest,
    NumericVerificationRequest,
    VerificationStatus,
    verify,
)


def valid_records() -> list[dict[str, object]]:
    return [asdict(question) for question in get_all_questions()]


def test_production_bank_has_valid_authored_questions() -> None:
    questions = get_all_questions()

    assert isinstance(questions, tuple)
    assert len(questions) > 12
    assert len({question.id for question in questions}) == len(questions)
    family_counts = Counter(question.verification_family for question in questions)
    assert family_counts["factorization"] >= 1
    assert family_counts["domain_condition"] >= 1
    for question in questions:
        assert isinstance(question, QuestionBankItem)
        assert all(
            isinstance(value, str) and value.strip()
            for field, value in asdict(question).items()
            if field != "difficulty"
        )
        assert isinstance(question.difficulty, int)
        assert question.difficulty in {1, 2, 3}
        assert question.verification_reference.strip()
        assert resolve_skill_code(question.skill_code) == question.skill_code
        assert is_mastery_bearing_skill(question.skill_code)
        definition = get_skill_definition(question.skill_code)
        assert definition is not None
        assert definition.verifier_family == question.verification_family


def test_production_questions_self_verify_as_correct() -> None:
    for question in get_all_questions():
        assert verify(_verification_request(question)).status is VerificationStatus.CORRECT


def test_all_deterministic_transfer_eligible_skills_are_covered() -> None:
    eligible_families = {
        "numeric",
        "expression_equivalence",
        "linear_equation",
        "factorization",
        "domain_condition",
    }
    eligible_skills = {
        skill.code
        for skill in get_controlled_skills()
        if is_mastery_bearing_skill(skill.code)
        and skill.verifier_family in eligible_families
    }
    covered_skills = {question.skill_code for question in get_all_questions()}

    assert eligible_skills <= covered_skills
    assert "algebra.rational_expression.simplify" not in eligible_skills


def test_non_mastery_supported_family_is_not_required_for_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_skills = tuple(question_bank.get_controlled_skills())
    source_skill = get_skill_definition("arithmetic.signed_number_operations")
    assert source_skill is not None
    non_mastery_skill = replace(source_skill, code="general.non_mastery_numeric")

    monkeypatch.setattr(
        question_bank,
        "get_controlled_skills",
        lambda: existing_skills + (non_mastery_skill,),
    )
    monkeypatch.setattr(
        question_bank,
        "is_mastery_bearing_skill",
        lambda skill_code: skill_code != non_mastery_skill.code,
    )

    assert len(question_bank._build_question_bank(valid_records())) == len(valid_records())


@pytest.mark.parametrize(
    ("family", "request_type", "reference_field", "answer_field"),
    [
        ("numeric", NumericVerificationRequest, "expected", "candidate"),
        ("expression_equivalence", ExpressionEquivalenceRequest, "left", "right"),
        ("linear_equation", LinearEquationRequest, "equation", "candidate"),
        ("factorization", FactorizationVerificationRequest, "reference", "candidate"),
        ("domain_condition", DomainConditionVerificationRequest, "reference", "candidate"),
    ],
)
def test_question_verification_requests_use_internal_reference_and_answer(
    family,
    request_type,
    reference_field,
    answer_field,
) -> None:
    question = next(
        item for item in get_all_questions() if item.verification_family == family
    )
    request = _verification_request(question)

    assert isinstance(request, request_type)
    assert getattr(request, reference_field) == question.verification_reference
    assert getattr(request, answer_field) == question.expected_answer


def test_get_all_questions_preserves_declaration_order() -> None:
    assert [question.id for question in get_all_questions()] == [
        "g8alg.signed-number-operations.001",
        "g8alg.signed-number-operations.002",
        "g8alg.signed-number-operations.003",
        "g8alg.signed-number-operations.004",
        "g8alg.distributive-property.001",
        "g8alg.distributive-property.002",
        "g8alg.distributive-property.003",
        "g8alg.combine-like-terms.001",
        "g8alg.combine-like-terms.002",
        "g8alg.combine-like-terms.003",
        "g8alg.expression-simplify.001",
        "g8alg.expression-simplify.002",
        "g8alg.expression-simplify.003",
        "g8alg.identity-basic.001",
        "g8alg.identity-basic.002",
        "g8alg.identity-basic.003",
        "g8alg.linear-equation.001",
        "g8alg.linear-equation.002",
        "g8alg.linear-equation.003",
        "g8alg.equivalent-transform.001",
        "g8alg.equivalent-transform.002",
        "g8alg.equivalent-transform.003",
        "g8alg.factorization.001",
        "g8alg.factorization.002",
        "g8alg.factorization.003",
        "g8alg.rational-expression-domain.001",
        "g8alg.rational-expression-domain.002",
        "g8alg.rational-expression-domain.003",
    ]


def test_question_bank_items_are_frozen() -> None:
    question = get_all_questions()[0]

    with pytest.raises(FrozenInstanceError):
        question.difficulty = 3  # type: ignore[misc]


def test_get_question_uses_exact_id_lookup() -> None:
    question = get_question("g8alg.linear-equation.001")

    assert question is not None
    assert question.skill_code == "algebra.linear_equation"
    assert get_question("unknown.question") is None


def test_skill_query_requires_canonical_skill_and_preserves_order() -> None:
    questions = get_questions_for_skill("arithmetic.signed_number_operations")

    assert isinstance(questions, tuple)
    assert [question.id for question in questions] == [
        "g8alg.signed-number-operations.001",
        "g8alg.signed-number-operations.002",
        "g8alg.signed-number-operations.003",
        "g8alg.signed-number-operations.004",
    ]
    assert get_questions_for_skill("unknown.skill") == ()
    assert get_questions_for_skill("linear equation") == ()


@pytest.mark.parametrize(
    ("question_id", "difficulty"),
    [
        ("g8alg.distributive-property.002", 1),
        ("g8alg.distributive-property.003", 2),
    ],
)
def test_new_distributive_property_items_are_authored_and_self_verify(
    question_id: str,
    difficulty: int,
) -> None:
    question = get_question(question_id)

    assert question is not None
    assert question.skill_code == "algebra.expression.distributive_property"
    assert question.verification_family == "expression_equivalence"
    assert question.difficulty == difficulty
    assert verify(_verification_request(question)).status is VerificationStatus.CORRECT


def test_distributive_property_reaches_targeted_coverage() -> None:
    assert len(
        get_questions_for_skill("algebra.expression.distributive_property")
    ) >= 3


@pytest.mark.parametrize(
    ("question_id", "difficulty"),
    [
        ("g8alg.combine-like-terms.002", 1),
        ("g8alg.combine-like-terms.003", 2),
    ],
)
def test_new_combine_like_terms_items_are_authored_and_self_verify(
    question_id: str,
    difficulty: int,
) -> None:
    question = get_question(question_id)

    assert question is not None
    assert question.skill_code == "algebra.expression.combine_like_terms"
    assert question.verification_family == "expression_equivalence"
    assert question.difficulty == difficulty
    assert verify(_verification_request(question)).status is VerificationStatus.CORRECT


def test_combine_like_terms_reaches_targeted_coverage() -> None:
    assert len(get_questions_for_skill("algebra.expression.combine_like_terms")) >= 3


@pytest.mark.parametrize(
    ("question_id", "difficulty"),
    [
        ("g8alg.expression-simplify.002", 1),
        ("g8alg.expression-simplify.003", 2),
    ],
)
def test_new_expression_simplify_items_are_authored_and_self_verify(
    question_id: str,
    difficulty: int,
) -> None:
    question = get_question(question_id)

    assert question is not None
    assert question.skill_code == "algebra.expression.simplify"
    assert question.verification_family == "expression_equivalence"
    assert question.difficulty == difficulty
    assert verify(_verification_request(question)).status is VerificationStatus.CORRECT


def test_expression_simplify_reaches_targeted_coverage() -> None:
    assert len(get_questions_for_skill("algebra.expression.simplify")) >= 3


@pytest.mark.parametrize(
    ("question_id", "difficulty"),
    [
        ("g8alg.identity-basic.002", 1),
        ("g8alg.identity-basic.003", 2),
    ],
)
def test_new_identity_basic_items_are_authored_and_self_verify(
    question_id: str,
    difficulty: int,
) -> None:
    question = get_question(question_id)

    assert question is not None
    assert question.skill_code == "algebra.identity.basic"
    assert question.verification_family == "expression_equivalence"
    assert question.difficulty == difficulty
    assert verify(_verification_request(question)).status is VerificationStatus.CORRECT


def test_identity_basic_reaches_targeted_coverage() -> None:
    assert len(get_questions_for_skill("algebra.identity.basic")) >= 3


@pytest.mark.parametrize(
    ("question_id", "difficulty"),
    [
        ("g8alg.factorization.002", 1),
        ("g8alg.factorization.003", 2),
    ],
)
def test_new_factorization_items_are_authored_and_self_verify(
    question_id: str,
    difficulty: int,
) -> None:
    question = get_question(question_id)

    assert question is not None
    assert question.skill_code == "algebra.factorization"
    assert question.verification_family == "factorization"
    assert question.difficulty == difficulty
    assert verify(_verification_request(question)).status is VerificationStatus.CORRECT


def test_factorization_reaches_targeted_coverage() -> None:
    assert len(get_questions_for_skill("algebra.factorization")) >= 3


@pytest.mark.parametrize(
    ("question_id", "difficulty"),
    [
        ("g8alg.rational-expression-domain.002", 1),
        ("g8alg.rational-expression-domain.003", 2),
    ],
)
def test_new_rational_expression_domain_items_are_authored_and_self_verify(
    question_id: str,
    difficulty: int,
) -> None:
    question = get_question(question_id)

    assert question is not None
    assert question.skill_code == "algebra.rational_expression.domain"
    assert question.verification_family == "domain_condition"
    assert question.difficulty == difficulty
    assert verify(_verification_request(question)).status is VerificationStatus.CORRECT


def test_rational_expression_domain_reaches_targeted_coverage() -> None:
    assert len(get_questions_for_skill("algebra.rational_expression.domain")) >= 3


def test_all_assessed_skills_reach_authored_content_floor() -> None:
    assessed_skills = (
        "arithmetic.signed_number_operations",
        "algebra.expression.distributive_property",
        "algebra.expression.combine_like_terms",
        "algebra.expression.simplify",
        "algebra.identity.basic",
        "algebra.linear_equation",
        "algebra.equation.equivalent_transform",
        "algebra.factorization",
        "algebra.rational_expression.domain",
    )

    assert all(len(get_questions_for_skill(skill_code)) >= 3 for skill_code in assessed_skills)


@pytest.mark.parametrize(
    ("question_id", "skill_code"),
    [
        ("g8alg.linear-equation.003", "algebra.linear_equation"),
        (
            "g8alg.equivalent-transform.003",
            "algebra.equation.equivalent_transform",
        ),
    ],
)
def test_new_equation_items_are_authored_and_self_verify(
    question_id: str,
    skill_code: str,
) -> None:
    question = get_question(question_id)

    assert question is not None
    assert question.skill_code == skill_code
    assert question.verification_family == "linear_equation"
    assert question.difficulty == 2
    assert verify(_verification_request(question)).status is VerificationStatus.CORRECT


def test_new_equation_items_raise_targeted_skill_coverage() -> None:
    assert len(get_questions_for_skill("algebra.linear_equation")) >= 3
    assert len(get_questions_for_skill("algebra.equation.equivalent_transform")) >= 3


def test_duplicate_question_id_is_rejected() -> None:
    records = valid_records()
    records[1]["id"] = records[0]["id"]

    with pytest.raises(ValueError, match="Duplicate question id"):
        _build_question_bank(records)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda records: records[0].pop("verification_reference"),
        lambda records: records[0].pop("difficulty"),
        lambda records: records[0].update({"extra": "field"}),
        lambda records: records[0].update({"problem_text": " "}),
        lambda records: records[0].update({"verification_reference": " "}),
        lambda records: records[0].update({"difficulty": "1"}),
        lambda records: records[0].update({"difficulty": 1.5}),
        lambda records: records[0].update({"difficulty": 0}),
        lambda records: records[0].update({"difficulty": 4}),
        lambda records: records[0].update({"difficulty": True}),
        lambda records: records[0].update({"difficulty": False}),
        lambda records: records[0].update({"skill_code": "unknown.skill"}),
        lambda records: records[0].update({"skill_code": "linear equation"}),
        lambda records: records[0].update({"verification_family": "manual_or_future"}),
        lambda records: records[0].update({"verification_family": "linear_equation"}),
    ],
)
def test_invalid_question_record_is_rejected(mutation) -> None:
    records = valid_records()
    mutation(records)

    with pytest.raises(ValueError):
        _build_question_bank(records)


def test_empty_question_bank_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one"):
        _build_question_bank([])


def test_family_counts_are_not_fixed() -> None:
    records = valid_records()
    skill_counts = Counter(record["skill_code"] for record in records)
    removable_index = next(
        index
        for index, record in enumerate(records)
        if skill_counts[record["skill_code"]] > 1
    )
    removed_record = records.pop(removable_index)

    rebuilt = _build_question_bank(records)
    original_family_counts = Counter(record["verification_family"] for record in valid_records())
    rebuilt_family_counts = Counter(item.verification_family for item in rebuilt)
    eligible_skills = {
        skill.code
        for skill in get_controlled_skills()
        if is_mastery_bearing_skill(skill.code)
        and skill.verifier_family
        in {
            "numeric",
            "expression_equivalence",
            "linear_equation",
            "factorization",
            "domain_condition",
        }
    }

    assert len(records) != 12
    assert len(rebuilt) == len(records)
    assert rebuilt_family_counts[removed_record["verification_family"]] == (
        original_family_counts[removed_record["verification_family"]] - 1
    )
    assert eligible_skills <= {item.skill_code for item in rebuilt}


def test_missing_eligible_skill_coverage_is_rejected() -> None:
    records = valid_records()
    records = [
        record
        for record in records
        if record["skill_code"] != "algebra.factorization"
    ]

    with pytest.raises(ValueError, match="deterministic transfer coverage"):
        _build_question_bank(records)


def test_manual_or_future_skill_is_not_required_for_coverage() -> None:
    records = valid_records()

    assert all(
        record["skill_code"] != "algebra.rational_expression.simplify"
        for record in records
    )
    assert len(_build_question_bank(records)) == len(records)


def test_self_invalid_verification_pair_is_rejected() -> None:
    records = valid_records()
    records[0]["expected_answer"] = "0"

    with pytest.raises(ValueError, match="verification pair"):
        _build_question_bank(records)

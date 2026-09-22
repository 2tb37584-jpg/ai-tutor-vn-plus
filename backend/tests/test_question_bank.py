from collections import Counter
from dataclasses import FrozenInstanceError, asdict

import pytest

from app.services.question_bank import (
    QuestionBankItem,
    _build_question_bank,
    _verification_request,
    get_all_questions,
    get_question,
    get_questions_for_skill,
)
from app.services.skill_registry import (
    get_skill_definition,
    is_mastery_bearing_skill,
    resolve_skill_code,
)
from app.services.verifier import (
    ExpressionEquivalenceRequest,
    LinearEquationRequest,
    NumericVerificationRequest,
    VerificationStatus,
    verify,
)


def valid_records() -> list[dict[str, object]]:
    return [asdict(question) for question in get_all_questions()]


def test_production_bank_has_valid_balanced_questions() -> None:
    questions = get_all_questions()

    assert isinstance(questions, tuple)
    assert len(questions) == 12
    assert len({question.id for question in questions}) == 12
    assert Counter(question.verification_family for question in questions) == {
        "numeric": 4,
        "expression_equivalence": 4,
        "linear_equation": 4,
    }
    assert Counter(question.difficulty for question in questions) == {1: 5, 2: 7}
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


@pytest.mark.parametrize(
    ("family", "request_type", "reference_field", "answer_field"),
    [
        ("numeric", NumericVerificationRequest, "expected", "candidate"),
        ("expression_equivalence", ExpressionEquivalenceRequest, "left", "right"),
        ("linear_equation", LinearEquationRequest, "equation", "candidate"),
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
        "g8alg.combine-like-terms.001",
        "g8alg.expression-simplify.001",
        "g8alg.identity-basic.001",
        "g8alg.linear-equation.001",
        "g8alg.linear-equation.002",
        "g8alg.equivalent-transform.001",
        "g8alg.equivalent-transform.002",
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


def test_wrong_total_is_rejected() -> None:
    with pytest.raises(ValueError, match="exactly 12"):
        _build_question_bank(valid_records()[:-1])


def test_wrong_family_distribution_is_rejected() -> None:
    records = valid_records()
    records[0]["skill_code"] = "algebra.expression.simplify"
    records[0]["verification_family"] = "expression_equivalence"

    with pytest.raises(ValueError, match="distribution"):
        _build_question_bank(records)


def test_self_invalid_verification_pair_is_rejected() -> None:
    records = valid_records()
    records[0]["expected_answer"] = "0"

    with pytest.raises(ValueError, match="verification pair"):
        _build_question_bank(records)

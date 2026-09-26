from dataclasses import fields

import pytest

import app.services.pilot_assessment_assignment as assignment
from app.services.pilot_assessment_assignment import (
    PilotSkillAssignment,
    assign_pilot_items,
)
from app.services.question_bank import QuestionBankItem, get_question


PILOT_SKILL_CODES = (
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


CANONICAL_ASSIGNMENTS = (
    PilotSkillAssignment(
        skill_code="arithmetic.signed_number_operations",
        pre_question_id="g8alg.signed-number-operations.001",
        learning_question_id="g8alg.signed-number-operations.002",
        post_question_id="g8alg.signed-number-operations.003",
    ),
    PilotSkillAssignment(
        skill_code="algebra.expression.distributive_property",
        pre_question_id="g8alg.distributive-property.001",
        learning_question_id="g8alg.distributive-property.002",
        post_question_id="g8alg.distributive-property.003",
    ),
    PilotSkillAssignment(
        skill_code="algebra.expression.combine_like_terms",
        pre_question_id="g8alg.combine-like-terms.001",
        learning_question_id="g8alg.combine-like-terms.002",
        post_question_id="g8alg.combine-like-terms.003",
    ),
    PilotSkillAssignment(
        skill_code="algebra.expression.simplify",
        pre_question_id="g8alg.expression-simplify.002",
        learning_question_id="g8alg.expression-simplify.003",
        post_question_id="g8alg.expression-simplify.001",
    ),
    PilotSkillAssignment(
        skill_code="algebra.identity.basic",
        pre_question_id="g8alg.identity-basic.001",
        learning_question_id="g8alg.identity-basic.002",
        post_question_id="g8alg.identity-basic.003",
    ),
    PilotSkillAssignment(
        skill_code="algebra.linear_equation",
        pre_question_id="g8alg.linear-equation.003",
        learning_question_id="g8alg.linear-equation.001",
        post_question_id="g8alg.linear-equation.002",
    ),
    PilotSkillAssignment(
        skill_code="algebra.equation.equivalent_transform",
        pre_question_id="g8alg.equivalent-transform.002",
        learning_question_id="g8alg.equivalent-transform.003",
        post_question_id="g8alg.equivalent-transform.001",
    ),
    PilotSkillAssignment(
        skill_code="algebra.factorization",
        pre_question_id="g8alg.factorization.003",
        learning_question_id="g8alg.factorization.001",
        post_question_id="g8alg.factorization.002",
    ),
    PilotSkillAssignment(
        skill_code="algebra.rational_expression.domain",
        pre_question_id="g8alg.rational-expression-domain.002",
        learning_question_id="g8alg.rational-expression-domain.003",
        post_question_id="g8alg.rational-expression-domain.001",
    ),
)


def test_canonical_assignment_vector() -> None:
    assert assign_pilot_items(assignment_seed="pilot-seed-a") == CANONICAL_ASSIGNMENTS


def test_same_seed_is_deterministic() -> None:
    first = assign_pilot_items(assignment_seed="pilot-seed-a")
    second = assign_pilot_items(assignment_seed="pilot-seed-a")

    assert first == second


def test_assignments_use_locked_blueprint_order() -> None:
    assignments = assign_pilot_items(assignment_seed="pilot-seed-b")

    assert tuple(item.skill_code for item in assignments) == PILOT_SKILL_CODES


def test_each_assignment_has_distinct_existing_skill_questions() -> None:
    assignments = assign_pilot_items(assignment_seed="pilot-seed-b")

    for item in assignments:
        question_ids = (
            item.pre_question_id,
            item.learning_question_id,
            item.post_question_id,
        )
        assert len(set(question_ids)) == 3
        for question_id in question_ids:
            question = get_question(question_id)
            assert question is not None
            assert question.skill_code == item.skill_code


def test_assignment_value_exposes_only_ids_and_skill() -> None:
    assert tuple(field.name for field in fields(PilotSkillAssignment)) == (
        "skill_code",
        "pre_question_id",
        "learning_question_id",
        "post_question_id",
    )


@pytest.mark.parametrize("seed", ["", None, 123])
def test_invalid_seed_is_rejected(seed: object) -> None:
    with pytest.raises(ValueError):
        assign_pilot_items(assignment_seed=seed)  # type: ignore[arg-type]


def test_insufficient_skill_coverage_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_lookup = assignment.get_questions_for_skill
    synthetic_item = QuestionBankItem(
        id="synthetic.only-item",
        skill_code="algebra.expression.simplify",
        problem_text="synthetic",
        verification_reference="x",
        expected_answer="x",
        verification_family="expression_equivalence",
        difficulty=1,
    )

    def lookup(skill_code: str) -> tuple[QuestionBankItem, ...]:
        if skill_code == "algebra.expression.simplify":
            return (synthetic_item,)
        return original_lookup(skill_code)

    monkeypatch.setattr(assignment, "get_questions_for_skill", lookup)

    with pytest.raises(ValueError):
        assign_pilot_items(assignment_seed="pilot-seed-a")

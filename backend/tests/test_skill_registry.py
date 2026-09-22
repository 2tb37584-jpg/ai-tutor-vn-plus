import pytest

from app.services.skill_registry import (
    UNKNOWN_SKILL_CODE,
    _build_registry,
    get_controlled_skills,
    get_direct_dependents,
    get_direct_prerequisites,
    get_skill_definition,
    is_mastery_bearing_skill,
    resolve_skill_code,
)


EXPECTED_CODES = {
    "arithmetic.signed_number_operations",
    "algebra.expression.distributive_property",
    "algebra.expression.combine_like_terms",
    "algebra.expression.simplify",
    "algebra.equation.equivalent_transform",
    "algebra.linear_equation",
    "algebra.identity.basic",
    "algebra.factorization",
    "algebra.rational_expression.domain",
    "algebra.rational_expression.simplify",
}


def test_exactly_ten_reviewed_skills_load() -> None:
    assert {skill.code for skill in get_controlled_skills()} == EXPECTED_CODES


def test_canonical_and_reviewed_aliases_resolve() -> None:
    assert resolve_skill_code("algebra.linear_equation") == "algebra.linear_equation"
    assert resolve_skill_code("phương trình bậc nhất một ẩn") == "algebra.linear_equation"
    assert resolve_skill_code("LINEAR EQUATION") == "algebra.linear_equation"
    assert resolve_skill_code("  LiNeAr   EqUaTiOn  ") == "algebra.linear_equation"
    assert resolve_skill_code("ｌｉｎｅａｒ　ｅｑｕａｔｉｏｎ") == "algebra.linear_equation"


def test_unknown_and_reserved_labels_do_not_create_skills() -> None:
    before = get_controlled_skills()
    for _ in range(3):
        assert resolve_skill_code("invented.mystery_skill") == UNKNOWN_SKILL_CODE
        assert resolve_skill_code("general.problem_solving") == UNKNOWN_SKILL_CODE
    assert get_controlled_skills() is before
    assert len(get_controlled_skills()) == 10
    assert not is_mastery_bearing_skill(UNKNOWN_SKILL_CODE)
    assert not is_mastery_bearing_skill("general.problem_solving")
    assert is_mastery_bearing_skill("algebra.linear_equation")


def test_get_skill_definition_requires_a_canonical_code() -> None:
    definition = get_skill_definition("algebra.linear_equation")

    assert definition is not None
    assert definition.code == "algebra.linear_equation"
    assert get_skill_definition("invented.mystery_skill") is None
    assert get_skill_definition("linear equation") is None


def test_direct_prerequisites_are_ordered_immutable_tuples() -> None:
    assert get_direct_prerequisites("arithmetic.signed_number_operations") == ()
    assert get_direct_prerequisites("algebra.expression.distributive_property") == (
        "arithmetic.signed_number_operations",
    )
    assert get_direct_prerequisites("algebra.expression.simplify") == (
        "algebra.expression.distributive_property",
        "algebra.expression.combine_like_terms",
    )
    prerequisites = get_direct_prerequisites("algebra.rational_expression.simplify")
    assert prerequisites == (
        "algebra.factorization",
        "algebra.rational_expression.domain",
    )
    assert isinstance(prerequisites, tuple)


def test_direct_prerequisites_reject_unknown_and_alias_codes() -> None:
    assert get_direct_prerequisites("invented.mystery_skill") == ()
    assert get_direct_prerequisites("linear equation") == ()


def test_direct_dependents_preserve_taxonomy_order() -> None:
    dependents = get_direct_dependents("arithmetic.signed_number_operations")

    assert dependents == (
        "algebra.expression.distributive_property",
        "algebra.expression.combine_like_terms",
    )
    assert isinstance(dependents, tuple)
    assert get_direct_dependents("algebra.expression.simplify") == (
        "algebra.equation.equivalent_transform",
        "algebra.factorization",
    )


def test_direct_dependents_reject_leaf_unknown_and_alias_codes() -> None:
    assert get_direct_dependents("algebra.rational_expression.simplify") == ()
    assert get_direct_dependents("invented.mystery_skill") == ()
    assert get_direct_dependents("linear equation") == ()


def test_all_prerequisites_are_controlled_skills() -> None:
    for skill in get_controlled_skills():
        for prerequisite in skill.prerequisites:
            assert resolve_skill_code(prerequisite) == prerequisite
            assert is_mastery_bearing_skill(prerequisite)


def skill(code: str, *, aliases: list[str] | None = None, prerequisites: list[str] | None = None) -> dict:
    return {
        "code": code,
        "name_vi": code,
        "subject": "math",
        "grade_min": 8,
        "grade_max": 8,
        "prerequisites": prerequisites or [],
        "aliases": aliases or [],
        "observable_mastery_evidence": [],
        "common_misconceptions": [],
        "verifier_family": "numeric",
    }


def taxonomy(*skills: dict) -> dict:
    return {"reserved_non_mastery_labels": ["general.problem_solving"], "skills": list(skills)}


def test_duplicate_skill_code_is_rejected() -> None:
    with pytest.raises(ValueError, match="Duplicate skill code"):
        _build_registry(taxonomy(skill("algebra.first"), skill("algebra.first")))


def test_normalized_alias_collision_is_rejected() -> None:
    with pytest.raises(ValueError, match="Alias collision"):
        _build_registry(
            taxonomy(
                skill("algebra.first", aliases=["Shared Alias"]),
                skill("algebra.second", aliases=["  shared   alias  "]),
            )
        )


def test_alias_collision_with_another_canonical_code_is_rejected() -> None:
    with pytest.raises(ValueError, match="Alias collision"):
        _build_registry(
            taxonomy(skill("algebra.first", aliases=["ALGEBRA.SECOND"]), skill("algebra.second"))
        )


def test_missing_prerequisite_is_rejected() -> None:
    with pytest.raises(ValueError, match="Missing prerequisite"):
        _build_registry(taxonomy(skill("algebra.first", prerequisites=["algebra.missing"])))


def test_prerequisite_cycle_is_rejected() -> None:
    with pytest.raises(ValueError, match="Prerequisite cycle"):
        _build_registry(
            taxonomy(
                skill("algebra.first", prerequisites=["algebra.second"]),
                skill("algebra.second", prerequisites=["algebra.first"]),
            )
        )


def test_reserved_label_cannot_be_a_mastery_skill() -> None:
    with pytest.raises(ValueError, match="Reserved label"):
        _build_registry(taxonomy(skill("general.problem_solving")))

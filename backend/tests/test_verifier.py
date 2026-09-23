from typing import cast

import pytest

import app.services.verifier as verifier
from app.services.verifier import (
    DomainConditionVerificationRequest,
    ExpressionEquivalenceRequest,
    FactorizationVerificationRequest,
    LinearEquationRequest,
    LinearEquationStatus,
    NumericVerificationRequest,
    ProblemFamily,
    VerificationStatus,
    classify_linear_equation,
    equivalent,
    solve_simple_equation,
    verify,
    verify_linear_equation_solution,
)


def test_equivalent_expressions() -> None:
    assert equivalent("(x+1)*(x+1)", "x^2+2*x+1")


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("x*(y+z)", "x*y+x*z"),
        ("(x+y)^2", "x^2+2*x*y+y^2"),
        ("x/2", "0.5*x"),
        ("(x+y)/4", "x/4+y/4"),
        ("1+1", "2"),
        ("1/2", "0.5"),
    ],
)
def test_supported_expressions_are_equivalent(left: str, right: str) -> None:
    assert equivalent(left, right)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("x+1", "x+2"),
        ("(x+1)^2", "x^2+1"),
    ],
)
def test_supported_expressions_can_be_non_equivalent(left: str, right: str) -> None:
    assert not equivalent(left, right)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("x/x", "1"),
        ("1/x", "1/x"),
        ("(x^2-1)/(x-1)", "x+1"),
        ("(x+y)/(x-y)", "(x+y)/(x-y)"),
    ],
)
def test_expression_equivalence_rejects_variable_denominators(
    left: str, right: str
) -> None:
    assert not equivalent(left, right)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("1/0", "1/0"),
        ("x/(2-2)", "0"),
        ("1/(3-3)", "1/(3-3)"),
    ],
)
def test_expression_equivalence_rejects_zero_denominators(
    left: str, right: str
) -> None:
    assert not equivalent(left, right)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("x^(1/2)", "x^(1/2)"),
        ("x^(-1)", "1/x"),
        ("(x+1)^(1/2)", "(x+1)^(1/2)"),
    ],
)
def test_expression_equivalence_rejects_unsupported_powers(
    left: str, right: str
) -> None:
    assert not equivalent(left, right)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("__import__('os')", "0"),
        ("sin(x)", "0"),
        ("sqrt(x)", "0"),
        ("x+1=2", "2"),
        ("x=x", "x"),
    ],
)
def test_expression_equivalence_rejects_unsafe_or_equation_input(
    left: str, right: str
) -> None:
    assert not equivalent(left, right)


def test_rejects_unsafe_characters() -> None:
    assert not equivalent("__import__('os')", "0")


def test_expression_verification_adapter_distinguishes_results() -> None:
    family = ProblemFamily.EXPRESSION_EQUIVALENCE

    assert (
        verify(ExpressionEquivalenceRequest(family, "(x+1)^2", "x^2+2*x+1")).status
        is VerificationStatus.CORRECT
    )
    assert (
        verify(ExpressionEquivalenceRequest(family, "x+1", "x+2")).status
        is VerificationStatus.INCORRECT
    )
    assert (
        verify(ExpressionEquivalenceRequest(family, "x/x", "1")).status
        is VerificationStatus.UNSUPPORTED
    )
    assert (
        verify(ExpressionEquivalenceRequest(family, "__import__('os')", "0")).status
        is VerificationStatus.UNSUPPORTED
    )


def test_expression_verification_adapter_handles_unexpected_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_runtime_error(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("unexpected verifier failure")

    monkeypatch.setattr(verifier, "simplify", raise_runtime_error)

    result = verify(
        ExpressionEquivalenceRequest(
            ProblemFamily.EXPRESSION_EQUIVALENCE,
            "x+1",
            "x+1",
        )
    )

    assert result.status is VerificationStatus.INDETERMINATE


def test_expression_verification_adapter_marks_parse_runtime_failure_indeterminate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_runtime_error(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("unexpected parser failure")

    monkeypatch.setattr(verifier, "_parse_supported_expression", raise_runtime_error)

    result = verify(
        ExpressionEquivalenceRequest(
            ProblemFamily.EXPRESSION_EQUIVALENCE,
            "x+1",
            "x+1",
        )
    )

    assert result.status is VerificationStatus.INDETERMINATE


@pytest.mark.parametrize(
    ("reference", "candidate"),
    [
        ("x^2-1", "(x-1)*(x+1)"),
        ("x^2+2*x+1", "(x+1)^2"),
        ("2*x+6", "2*(x+3)"),
    ],
)
def test_factorization_verification_accepts_equivalent_factored_forms(
    reference: str,
    candidate: str,
) -> None:
    result = verify(
        FactorizationVerificationRequest(
            ProblemFamily.FACTORIZATION,
            reference,
            candidate,
        )
    )

    assert result.status is VerificationStatus.CORRECT


@pytest.mark.parametrize(
    ("reference", "candidate"),
    [
        ("x^2-1", "x^2-1"),
        ("x^2+2*x+1", "x^2+2*x+1"),
        ("x^2-1", "(x-1)*(x-1)"),
    ],
)
def test_factorization_verification_rejects_expanded_or_wrong_factors(
    reference: str,
    candidate: str,
) -> None:
    result = verify(
        FactorizationVerificationRequest(
            ProblemFamily.FACTORIZATION,
            reference,
            candidate,
        )
    )

    assert result.status is VerificationStatus.INCORRECT


@pytest.mark.parametrize(
    ("reference", "candidate"),
    [
        ("x^2-1", "1*(x^2-1)"),
        ("x^2-1", "-1*(-x^2+1)"),
        ("x^2-1", "2*(x^2-1)/2"),
        ("x^2-1", "-2*(-x^2+1)/2"),
        ("x^2-1", "2*(x^2-1)*0.5"),
        ("x^2-1", "-2*(-x^2+1)*0.5"),
        ("x^2+x+1", "x*(x+1)+1"),
    ],
)
def test_factorization_verification_rejects_trivial_or_additive_wrappers(
    reference: str,
    candidate: str,
) -> None:
    result = verify(
        FactorizationVerificationRequest(
            ProblemFamily.FACTORIZATION,
            reference,
            candidate,
        )
    )

    assert result.status is VerificationStatus.INCORRECT


@pytest.mark.parametrize(
    "candidate",
    ["__import__('os')", "1/x", "a*(x+1)"],
)
def test_factorization_verification_rejects_unsupported_input(candidate: str) -> None:
    result = verify(
        FactorizationVerificationRequest(
            ProblemFamily.FACTORIZATION,
            "x^2-1",
            candidate,
        )
    )

    assert result.status is VerificationStatus.UNSUPPORTED


def test_factorization_verification_rejects_unsupported_reference() -> None:
    result = verify(
        FactorizationVerificationRequest(
            ProblemFamily.FACTORIZATION,
            "1/x",
            "(x-1)*(x+1)",
        )
    )

    assert result.status is VerificationStatus.UNSUPPORTED


def test_factorization_verification_rejects_mismatched_family() -> None:
    result = verify(
        FactorizationVerificationRequest(
            ProblemFamily.NUMERIC,
            "x^2-1",
            "(x-1)*(x+1)",
        )
    )

    assert result.status is VerificationStatus.UNSUPPORTED


def test_factorization_verification_marks_internal_failure_indeterminate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_runtime_error(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("unexpected simplification failure")

    monkeypatch.setattr(verifier, "simplify", raise_runtime_error)

    result = verify(
        FactorizationVerificationRequest(
            ProblemFamily.FACTORIZATION,
            "x^2-1",
            "(x-1)*(x+1)",
        )
    )

    assert result.status is VerificationStatus.INDETERMINATE


@pytest.mark.parametrize(
    ("reference", "candidate"),
    [
        ("-3,2", "x != -3, x != 2"),
        ("-3,2", "x ≠ 2; x ≠ -3"),
        ("1/2", "x != 2/4"),
        ("-3,2", "x != -3, x != 2, x != 2"),
        ("-3,2,2,-3", "x != -3, x != 2"),
    ],
)
def test_domain_condition_verification_accepts_equal_excluded_sets(
    reference: str,
    candidate: str,
) -> None:
    result = verify(
        DomainConditionVerificationRequest(
            ProblemFamily.DOMAIN_CONDITION,
            reference,
            candidate,
        )
    )

    assert result.status is VerificationStatus.CORRECT


def test_domain_condition_verification_supports_non_default_variable() -> None:
    result = verify(
        DomainConditionVerificationRequest(
            ProblemFamily.DOMAIN_CONDITION,
            "1/2",
            "y != 2/4",
            variable="y",
        )
    )

    assert result.status is VerificationStatus.CORRECT


@pytest.mark.parametrize(
    "candidate",
    [
        "x != -3",
        "x != -3, x != 2, x != 5",
        "x != 3, x != 2",
    ],
)
def test_domain_condition_verification_rejects_different_excluded_sets(
    candidate: str,
) -> None:
    result = verify(
        DomainConditionVerificationRequest(
            ProblemFamily.DOMAIN_CONDITION,
            "-3,2",
            candidate,
        )
    )

    assert result.status is VerificationStatus.INCORRECT


@pytest.mark.parametrize(
    ("reference", "candidate"),
    [
        ("", "x != 2"),
        ("-3,,2", "x != -3, x != 2"),
        ("-3,2", ""),
        ("-3,2", "x != 2.0"),
        ("-3,2", "x > 2"),
        ("-3,2", "{x | x != 2}"),
        ("-3,2", "y != 2"),
        ("-3,2", "w != 2"),
        ("-3,2", "x != a"),
        ("-3,2", "x != __import__('os')"),
    ],
)
def test_domain_condition_verification_rejects_unsupported_input(
    reference: str,
    candidate: str,
) -> None:
    result = verify(
        DomainConditionVerificationRequest(
            ProblemFamily.DOMAIN_CONDITION,
            reference,
            candidate,
        )
    )

    assert result.status is VerificationStatus.UNSUPPORTED


def test_domain_condition_verification_rejects_unsupported_request_variable() -> None:
    result = verify(
        DomainConditionVerificationRequest(
            ProblemFamily.DOMAIN_CONDITION,
            "2",
            "w != 2",
            variable="w",
        )
    )

    assert result.status is VerificationStatus.UNSUPPORTED


def test_domain_condition_verification_rejects_mismatched_family() -> None:
    result = verify(
        DomainConditionVerificationRequest(
            ProblemFamily.NUMERIC,
            "2",
            "x != 2",
        )
    )

    assert result.status is VerificationStatus.UNSUPPORTED


def test_domain_condition_verification_reports_unexpected_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_runtime_error(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("unexpected domain parser failure")

    monkeypatch.setattr(verifier, "_parse_domain_condition_reference", raise_runtime_error)

    result = verify(
        DomainConditionVerificationRequest(
            ProblemFamily.DOMAIN_CONDITION,
            "2",
            "x != 2",
        )
    )

    assert result.status is VerificationStatus.INDETERMINATE


@pytest.mark.parametrize(
    ("equation", "variable", "solution"),
    [
        ("2*x+3=7", "x", ["2"]),
        (" 2 * x + 3 = 7 ", "x", ["2"]),
        ("3*(x-2)=9", "x", ["5"]),
        ("2*y+3=7", "y", ["2"]),
    ],
)
def test_solves_supported_linear_equations(equation: str, variable: str, solution: list[str]) -> None:
    assert solve_simple_equation(equation, variable) == solution


def test_nonzero_constant_denominators_remain_supported() -> None:
    assert solve_simple_equation("x/2+1=3") == ["4"]
    assert solve_simple_equation("x/(2+2)=2") == ["8"]


def test_classifies_constant_equations() -> None:
    assert classify_linear_equation("x+1=x+2").status is LinearEquationStatus.NO_SOLUTION
    assert (
        classify_linear_equation("x+1=x+1").status
        is LinearEquationStatus.INFINITELY_MANY_SOLUTIONS
    )
    assert solve_simple_equation("x+1=x+2") == []
    assert solve_simple_equation("x+1=x+1") == []


@pytest.mark.parametrize(
    ("equation", "variable"),
    [
        ("2*x+3", "x"),
        ("x=2=3", "x"),
        ("=2", "x"),
        ("x=", "x"),
        ("2*x+y=7", "x"),
        ("x^2=4", "x"),
        ("x*x=4", "x"),
        ("1/x=2", "x"),
        ("x/x=1", "x"),
        ("(x+1)/(x+1)=1", "x"),
        ("x/x+x=3", "x"),
        ("1/(x+1)=2", "x"),
        ("x/0=1", "x"),
        ("1/0=2", "x"),
        ("x/(2-2)=1", "x"),
        ("1/(3-3)=5", "x"),
        ("__import__('os')=0", "x"),
        ("sin(x)=0", "x"),
        ("2*x+3=7", "a"),
    ],
)
def test_rejects_invalid_or_unsupported_equations(equation: str, variable: str) -> None:
    assert classify_linear_equation(equation, variable).status is LinearEquationStatus.INVALID
    assert solve_simple_equation(equation, variable) == []


@pytest.mark.parametrize(
    ("candidate", "verified"),
    [
        ("2", True),
        ("3", False),
        ("1+1", True),
        ("x", False),
        ("__import__('os')", False),
        ("1/0", False),
    ],
)
def test_verifies_candidate_solution(candidate: str, verified: bool) -> None:
    assert verify_linear_equation_solution("2*x+3=7", candidate) is verified


def test_candidate_requires_valid_unique_supported_equation() -> None:
    assert not verify_linear_equation_solution("x^2=4", "2")
    assert not verify_linear_equation_solution("2*x+y=7", "2")
    assert not verify_linear_equation_solution("x+1=x+1", "2")


def test_verifies_supported_y_equation() -> None:
    assert verify_linear_equation_solution("2*y+3=7", "2", variable="y")


def test_linear_equation_verification_adapter_distinguishes_results() -> None:
    family = ProblemFamily.LINEAR_EQUATION

    assert (
        verify(LinearEquationRequest(family, "2*x+3=7", "2")).status
        is VerificationStatus.CORRECT
    )
    assert (
        verify(LinearEquationRequest(family, "2*x+3=7", "3")).status
        is VerificationStatus.INCORRECT
    )
    assert (
        verify(LinearEquationRequest(family, "x^2=4", "2")).status
        is VerificationStatus.UNSUPPORTED
    )
    assert (
        verify(LinearEquationRequest(family, "2*x+y=7", "2")).status
        is VerificationStatus.UNSUPPORTED
    )
    assert (
        verify(LinearEquationRequest(family, "x+1=x+1", "2")).status
        is VerificationStatus.UNSUPPORTED
    )
    assert (
        verify(LinearEquationRequest(family, "2*x+3=7", "x")).status
        is VerificationStatus.UNSUPPORTED
    )
    assert (
        verify(LinearEquationRequest(family, "2*x+3=7", "1/0")).status
        is VerificationStatus.UNSUPPORTED
    )


def test_linear_adapter_exposes_internal_failure_without_changing_public_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_runtime_error(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("unexpected simplification failure")

    monkeypatch.setattr(verifier, "simplify", raise_runtime_error)

    assert (
        verify(LinearEquationRequest(ProblemFamily.LINEAR_EQUATION, "2*x+3=7", "2")).status
        is VerificationStatus.INDETERMINATE
    )
    assert (
        classify_linear_equation("2*x+3=7").status
        is LinearEquationStatus.INVALID
    )


def test_verification_router_rejects_unregistered_or_mismatched_family() -> None:
    unknown_family = cast(ProblemFamily, "unregistered")

    assert verify(
        ExpressionEquivalenceRequest(unknown_family, "x+1", "x+1")
    ).status is VerificationStatus.UNSUPPORTED
    assert verify(
        LinearEquationRequest(ProblemFamily.EXPRESSION_EQUIVALENCE, "2*x=4", "2")
    ).status is VerificationStatus.UNSUPPORTED


@pytest.mark.parametrize(
    ("expected", "candidate"),
    [
        ("4", "4"),
        ("-8", "-8"),
        ("1/2", "0.5"),
        ("0.1", "1/10"),
        ("3/2", "1.5"),
        ("3.14", "3.140"),
        (" 1/2 ", "0.5"),
    ],
)
def test_numeric_verification_adapter_compares_exact_values(
    expected: str,
    candidate: str,
) -> None:
    result = verify(
        NumericVerificationRequest(ProblemFamily.NUMERIC, expected, candidate)
    )

    assert result.status is VerificationStatus.CORRECT


def test_numeric_verification_adapter_reports_different_values() -> None:
    assert (
        verify(NumericVerificationRequest(ProblemFamily.NUMERIC, "3", "4")).status
        is VerificationStatus.INCORRECT
    )
    assert (
        verify(NumericVerificationRequest(ProblemFamily.NUMERIC, "0.333", "1/3")).status
        is VerificationStatus.INCORRECT
    )


@pytest.mark.parametrize(
    "literal",
    [
        "1/0",
        "x",
        "1+2",
        "sqrt(2)",
        "pi",
        "1e-3",
        "25%",
        "3 cm",
        "NaN",
        "Infinity",
        "1,5",
        "[1,2]",
        "1 < 2",
        "(1,2)",
        "1+2i",
        "1 1/2",
    ],
)
def test_numeric_verification_adapter_rejects_unsupported_literals(literal: str) -> None:
    result = verify(
        NumericVerificationRequest(ProblemFamily.NUMERIC, "1", literal)
    )

    assert result.status is VerificationStatus.UNSUPPORTED


def test_numeric_verification_adapter_handles_unexpected_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_runtime_error(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("unexpected numeric parser failure")

    monkeypatch.setattr(verifier, "_parse_exact_numeric_literal", raise_runtime_error)

    result = verify(NumericVerificationRequest(ProblemFamily.NUMERIC, "1", "1"))

    assert result.status is VerificationStatus.INDETERMINATE


def test_numeric_verification_router_rejects_mismatched_or_unknown_family() -> None:
    unknown_family = cast(ProblemFamily, "unregistered")

    assert verify(
        NumericVerificationRequest(ProblemFamily.EXPRESSION_EQUIVALENCE, "1", "1")
    ).status is VerificationStatus.UNSUPPORTED
    assert verify(
        NumericVerificationRequest(unknown_family, "1", "1")
    ).status is VerificationStatus.UNSUPPORTED

import pytest

from app.services.verifier import (
    LinearEquationStatus,
    classify_linear_equation,
    equivalent,
    solve_simple_equation,
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

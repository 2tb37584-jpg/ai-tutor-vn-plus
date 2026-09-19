import re
from dataclasses import dataclass
from enum import Enum

from sympy import (
    Add,
    Expr,
    Float,
    Integer,
    Mul,
    Poly,
    Pow,
    Rational,
    Symbol,
    nan,
    oo,
    preorder_traversal,
    simplify,
    zoo,
)
from sympy.parsing.sympy_parser import convert_xor, parse_expr, standard_transformations


_ALLOWED = re.compile(r"^[0-9xyzXYZ+\-*/^().=\s]+$")
_TRANSFORMS = standard_transformations + (convert_xor,)
_SYMBOLS = {name: Symbol(name) for name in ("x", "y", "z")}
_PARSE_GLOBALS = {
    "Add": Add,
    "Float": Float,
    "Integer": Integer,
    "Mul": Mul,
    "Pow": Pow,
    "Rational": Rational,
}


class LinearEquationStatus(str, Enum):
    UNIQUE_SOLUTION = "unique_solution"
    NO_SOLUTION = "no_solution"
    INFINITELY_MANY_SOLUTIONS = "infinitely_many_solutions"
    INVALID = "invalid"


@dataclass(frozen=True)
class LinearEquationResult:
    status: LinearEquationStatus
    solution: Expr | None = None


def _parse_safe(expr: str, *, evaluate: bool = True) -> Expr:
    if not expr.strip() or not _ALLOWED.fullmatch(expr):
        raise ValueError("Expression contains unsupported characters")
    return parse_expr(
        expr,
        local_dict=_SYMBOLS,
        global_dict=_PARSE_GLOBALS,
        transformations=_TRANSFORMS,
        evaluate=evaluate,
    )


def _has_unsupported_denominator(expr: Expr, symbol: Symbol) -> bool:
    for node in preorder_traversal(expr):
        if not (
            isinstance(node, Pow)
            and node.exp.is_number
            and node.exp.is_negative is True
        ):
            continue
        if symbol in node.base.free_symbols or simplify(node.base) == 0:
            return True
    return False


def _is_non_finite(expr: Expr) -> bool:
    return expr.is_finite is False or expr.has(zoo, nan, oo, -oo)


def equivalent(left: str, right: str) -> bool:
    """Limited deterministic equivalence checker for simple school algebra."""
    try:
        return simplify(_parse_safe(left) - _parse_safe(right)) == 0
    except Exception:
        return False


def classify_linear_equation(equation: str, variable: str = "x") -> LinearEquationResult:
    """Classify a supported one-variable linear equation without raising parse errors."""
    if variable not in _SYMBOLS or equation.count("=") != 1:
        return LinearEquationResult(LinearEquationStatus.INVALID)

    lhs_text, rhs_text = equation.split("=", 1)
    if not lhs_text.strip() or not rhs_text.strip():
        return LinearEquationResult(LinearEquationStatus.INVALID)

    symbol = _SYMBOLS[variable]
    try:
        lhs = _parse_safe(lhs_text, evaluate=False)
        rhs = _parse_safe(rhs_text, evaluate=False)
        if (lhs.free_symbols | rhs.free_symbols) - {symbol}:
            return LinearEquationResult(LinearEquationStatus.INVALID)
        if _has_unsupported_denominator(lhs, symbol) or _has_unsupported_denominator(rhs, symbol):
            return LinearEquationResult(LinearEquationStatus.INVALID)

        difference = simplify(lhs - rhs)
        if _is_non_finite(difference):
            return LinearEquationResult(LinearEquationStatus.INVALID)
        if difference == 0:
            return LinearEquationResult(LinearEquationStatus.INFINITELY_MANY_SOLUTIONS)

        polynomial = Poly(difference, symbol)
        degree = polynomial.degree()
        if degree > 1:
            return LinearEquationResult(LinearEquationStatus.INVALID)
        if degree == 0:
            return LinearEquationResult(LinearEquationStatus.NO_SOLUTION)

        coefficient, constant = polynomial.all_coeffs()
        if any(_is_non_finite(value) or value.is_finite is not True for value in (coefficient, constant)):
            return LinearEquationResult(LinearEquationStatus.INVALID)
        solution = simplify(-constant / coefficient)
        return LinearEquationResult(LinearEquationStatus.UNIQUE_SOLUTION, solution)
    except Exception:
        return LinearEquationResult(LinearEquationStatus.INVALID)


def verify_linear_equation_solution(
    equation: str,
    candidate: str,
    variable: str = "x",
) -> bool:
    """Return whether a safe scalar candidate equals the equation's unique solution."""
    result = classify_linear_equation(equation, variable)
    if result.status is not LinearEquationStatus.UNIQUE_SOLUTION or result.solution is None:
        return False

    try:
        candidate_value = _parse_safe(candidate)
        if candidate_value.free_symbols or candidate_value.is_finite is not True:
            return False
        return simplify(candidate_value - result.solution) == 0
    except Exception:
        return False


def solve_simple_equation(equation: str, variable: str = "x") -> list[str]:
    """Compatibility wrapper returning one string only for a unique supported solution."""
    result = classify_linear_equation(equation, variable)
    if result.status is LinearEquationStatus.UNIQUE_SOLUTION and result.solution is not None:
        return [str(result.solution)]
    return []

import re
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction

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
from sympy.polys.polyerrors import PolynomialError


_ALLOWED = re.compile(r"^[0-9xyzXYZ+\-*/^().=\s]+$")
_NUMERIC_LITERAL = re.compile(r"^[+-]?(?:\d+|\d+\.\d+|\d+/\d+)$")
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


class ProblemFamily(str, Enum):
    EXPRESSION_EQUIVALENCE = "expression_equivalence"
    FACTORIZATION = "factorization"
    LINEAR_EQUATION = "linear_equation"
    NUMERIC = "numeric"


class VerificationStatus(str, Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    UNSUPPORTED = "unsupported"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class VerificationResult:
    status: VerificationStatus


@dataclass(frozen=True)
class ExpressionEquivalenceRequest:
    family: ProblemFamily
    left: str
    right: str


@dataclass(frozen=True)
class FactorizationVerificationRequest:
    family: ProblemFamily
    reference: str
    candidate: str


@dataclass(frozen=True)
class LinearEquationRequest:
    family: ProblemFamily
    equation: str
    candidate: str
    variable: str = "x"


@dataclass(frozen=True)
class NumericVerificationRequest:
    family: ProblemFamily
    expected: str
    candidate: str


VerificationRequest = (
    ExpressionEquivalenceRequest
    | FactorizationVerificationRequest
    | LinearEquationRequest
    | NumericVerificationRequest
)


class _UnsupportedVerificationInput(Exception):
    """Expected parser or algebra-domain rejection for adapter verification."""


_KNOWN_VALIDATION_ERRORS = (ValueError, TypeError, SyntaxError, PolynomialError)


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


def _has_unsupported_expression_denominator(expr: Expr) -> bool:
    """Reject symbolic and deterministically zero denominators before cancellation."""
    for node in preorder_traversal(expr):
        if not (
            isinstance(node, Pow)
            and node.exp.is_number
            and node.exp.is_negative is True
        ):
            continue
        if node.base.free_symbols or simplify(node.base) == 0:
            return True
    return False


def _parse_supported_expression(text: str) -> Expr:
    if "=" in text:
        raise ValueError("Equations are not expression-equivalence inputs")

    expression = _parse_safe(text, evaluate=False)
    supported_symbols = set(_SYMBOLS.values())
    if expression.free_symbols - supported_symbols:
        raise ValueError("Expression contains an unsupported symbol")
    if _has_unsupported_expression_denominator(expression):
        raise ValueError("Expression contains an unsupported denominator")
    if _is_non_finite(expression):
        raise ValueError("Expression is non-finite")

    symbols = sorted(expression.free_symbols, key=lambda symbol: symbol.name)
    if symbols:
        polynomial = Poly(expression, *symbols)
        if any(
            _is_non_finite(coefficient) or coefficient.is_finite is not True
            for coefficient in polynomial.coeffs()
        ):
            raise ValueError("Expression contains a non-finite coefficient")
    else:
        value = simplify(expression)
        if _is_non_finite(value) or value.is_finite is not True:
            raise ValueError("Expression is non-finite")
    return expression


def _verify_expression_equivalence(
    request: ExpressionEquivalenceRequest,
) -> VerificationResult:
    try:
        left_expression = _parse_supported_expression(request.left)
        right_expression = _parse_supported_expression(request.right)
    except _KNOWN_VALIDATION_ERRORS:
        return VerificationResult(VerificationStatus.UNSUPPORTED)
    except Exception:
        return VerificationResult(VerificationStatus.INDETERMINATE)

    try:
        difference = simplify(left_expression - right_expression)
        if _is_non_finite(difference):
            return VerificationResult(VerificationStatus.UNSUPPORTED)
        status = (
            VerificationStatus.CORRECT
            if difference == 0
            else VerificationStatus.INCORRECT
        )
        return VerificationResult(status)
    except Exception:
        return VerificationResult(VerificationStatus.INDETERMINATE)


def _has_accepted_factored_structure(expression: Expr) -> bool:
    supported_symbols = set(_SYMBOLS.values())
    if isinstance(expression, Mul):
        meaningful_factors = tuple(
            factor
            for factor in expression.args
            if factor not in (Integer(1), Integer(-1))
        )
        variable_factors = tuple(
            factor
            for factor in meaningful_factors
            if factor.free_symbols & supported_symbols
        )
        numeric_factors = tuple(
            factor
            for factor in meaningful_factors
            if not factor.free_symbols and factor.is_number is True
        )
        if len(variable_factors) == 1 and numeric_factors:
            numeric_product = simplify(Mul(*numeric_factors))
            if (
                simplify(numeric_product - 1) == 0
                or simplify(numeric_product + 1) == 0
            ):
                return False
        return len(meaningful_factors) >= 2 and bool(variable_factors)
    if isinstance(expression, Pow):
        return (
            isinstance(expression.exp, Integer)
            and expression.exp > 1
            and bool(expression.base.free_symbols & supported_symbols)
        )
    return False


def _verify_factorization(
    request: FactorizationVerificationRequest,
) -> VerificationResult:
    try:
        reference_expression = _parse_supported_expression(request.reference)
        candidate_expression = _parse_supported_expression(request.candidate)
    except _KNOWN_VALIDATION_ERRORS:
        return VerificationResult(VerificationStatus.UNSUPPORTED)
    except Exception:
        return VerificationResult(VerificationStatus.INDETERMINATE)

    try:
        if not _has_accepted_factored_structure(candidate_expression):
            return VerificationResult(VerificationStatus.INCORRECT)
        difference = simplify(reference_expression - candidate_expression)
        if _is_non_finite(difference):
            return VerificationResult(VerificationStatus.UNSUPPORTED)
        status = (
            VerificationStatus.CORRECT
            if difference == 0
            else VerificationStatus.INCORRECT
        )
        return VerificationResult(status)
    except Exception:
        return VerificationResult(VerificationStatus.INDETERMINATE)


def equivalent(left: str, right: str) -> bool:
    """Compare finite polynomial school-algebra expressions deterministically."""
    try:
        left_expression = _parse_supported_expression(left)
        right_expression = _parse_supported_expression(right)
        difference = simplify(left_expression - right_expression)
        return not _is_non_finite(difference) and difference == 0
    except Exception:
        return False


def _classify_linear_equation_detailed(
    equation: str,
    variable: str = "x",
) -> LinearEquationResult:
    if variable not in _SYMBOLS or equation.count("=") != 1:
        raise _UnsupportedVerificationInput

    lhs_text, rhs_text = equation.split("=", 1)
    if not lhs_text.strip() or not rhs_text.strip():
        raise _UnsupportedVerificationInput

    symbol = _SYMBOLS[variable]
    try:
        lhs = _parse_safe(lhs_text, evaluate=False)
        rhs = _parse_safe(rhs_text, evaluate=False)
    except _KNOWN_VALIDATION_ERRORS as error:
        raise _UnsupportedVerificationInput from error

    if (lhs.free_symbols | rhs.free_symbols) - {symbol}:
        raise _UnsupportedVerificationInput
    if _has_unsupported_denominator(lhs, symbol) or _has_unsupported_denominator(rhs, symbol):
        raise _UnsupportedVerificationInput

    difference = simplify(lhs - rhs)
    if _is_non_finite(difference):
        raise _UnsupportedVerificationInput
    if difference == 0:
        return LinearEquationResult(LinearEquationStatus.INFINITELY_MANY_SOLUTIONS)

    try:
        polynomial = Poly(difference, symbol)
    except PolynomialError as error:
        raise _UnsupportedVerificationInput from error
    degree = polynomial.degree()
    if degree > 1:
        return LinearEquationResult(LinearEquationStatus.INVALID)
    if degree == 0:
        return LinearEquationResult(LinearEquationStatus.NO_SOLUTION)

    coefficient, constant = polynomial.all_coeffs()
    if any(_is_non_finite(value) or value.is_finite is not True for value in (coefficient, constant)):
        raise _UnsupportedVerificationInput
    solution = simplify(-constant / coefficient)
    return LinearEquationResult(LinearEquationStatus.UNIQUE_SOLUTION, solution)


def classify_linear_equation(equation: str, variable: str = "x") -> LinearEquationResult:
    """Classify a supported one-variable linear equation without raising parse errors."""
    try:
        return _classify_linear_equation_detailed(equation, variable)
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


def _verify_linear_equation(request: LinearEquationRequest) -> VerificationResult:
    try:
        result = _classify_linear_equation_detailed(
            request.equation,
            request.variable,
        )
    except _UnsupportedVerificationInput:
        return VerificationResult(VerificationStatus.UNSUPPORTED)
    except Exception:
        return VerificationResult(VerificationStatus.INDETERMINATE)


    if result.status is not LinearEquationStatus.UNIQUE_SOLUTION or result.solution is None:
        return VerificationResult(VerificationStatus.UNSUPPORTED)

    try:
        candidate_value = _parse_safe(request.candidate)
    except _KNOWN_VALIDATION_ERRORS:
        return VerificationResult(VerificationStatus.UNSUPPORTED)
    except Exception:
        return VerificationResult(VerificationStatus.INDETERMINATE)

    if candidate_value.free_symbols or candidate_value.is_finite is not True:
        return VerificationResult(VerificationStatus.UNSUPPORTED)
    if _is_non_finite(result.solution):
        return VerificationResult(VerificationStatus.UNSUPPORTED)

    try:
        status = (
            VerificationStatus.CORRECT
            if simplify(candidate_value - result.solution) == 0
            else VerificationStatus.INCORRECT
        )
        return VerificationResult(status)
    except Exception:
        return VerificationResult(VerificationStatus.INDETERMINATE)


def _parse_exact_numeric_literal(text: str) -> Fraction:
    if not isinstance(text, str):
        raise _UnsupportedVerificationInput

    literal = text.strip()
    if not _NUMERIC_LITERAL.fullmatch(literal):
        raise _UnsupportedVerificationInput

    try:
        return Fraction(literal)
    except (ValueError, ZeroDivisionError) as error:
        raise _UnsupportedVerificationInput from error


def _verify_numeric(request: NumericVerificationRequest) -> VerificationResult:
    try:
        expected = _parse_exact_numeric_literal(request.expected)
        candidate = _parse_exact_numeric_literal(request.candidate)
    except _UnsupportedVerificationInput:
        return VerificationResult(VerificationStatus.UNSUPPORTED)
    except Exception:
        return VerificationResult(VerificationStatus.INDETERMINATE)

    status = (
        VerificationStatus.CORRECT
        if expected == candidate
        else VerificationStatus.INCORRECT
    )
    return VerificationResult(status)


def verify(request: VerificationRequest) -> VerificationResult:
    """Route an explicitly classified deterministic verification request."""
    if request.family is ProblemFamily.EXPRESSION_EQUIVALENCE:
        if not isinstance(request, ExpressionEquivalenceRequest):
            return VerificationResult(VerificationStatus.UNSUPPORTED)
        return _verify_expression_equivalence(request)
    if request.family is ProblemFamily.FACTORIZATION:
        if not isinstance(request, FactorizationVerificationRequest):
            return VerificationResult(VerificationStatus.UNSUPPORTED)
        return _verify_factorization(request)
    if request.family is ProblemFamily.LINEAR_EQUATION:
        if not isinstance(request, LinearEquationRequest):
            return VerificationResult(VerificationStatus.UNSUPPORTED)
        return _verify_linear_equation(request)
    if request.family is ProblemFamily.NUMERIC:
        if not isinstance(request, NumericVerificationRequest):
            return VerificationResult(VerificationStatus.UNSUPPORTED)
        return _verify_numeric(request)
    return VerificationResult(VerificationStatus.UNSUPPORTED)

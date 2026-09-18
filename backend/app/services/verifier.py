import re
from sympy import Eq, Symbol, simplify, solve
from sympy.parsing.sympy_parser import parse_expr, standard_transformations, convert_xor

_ALLOWED = re.compile(r"^[0-9xyzXYZ+\-*/^().=\s]+$")
_TRANSFORMS = standard_transformations + (convert_xor,)


def _parse_safe(expr: str):
    if not _ALLOWED.fullmatch(expr):
        raise ValueError("Expression contains unsupported characters")
    local = {"x": Symbol("x"), "y": Symbol("y"), "z": Symbol("z")}
    return parse_expr(expr, local_dict=local, transformations=_TRANSFORMS, evaluate=True)


def equivalent(left: str, right: str) -> bool:
    """Limited deterministic equivalence checker for simple school algebra."""
    try:
        return simplify(_parse_safe(left) - _parse_safe(right)) == 0
    except Exception:
        return False


def solve_simple_equation(equation: str, variable: str = "x") -> list[str]:
    try:
        if equation.count("=") != 1:
            return []
        lhs, rhs = equation.split("=", 1)
        symbol = Symbol(variable)
        result = solve(Eq(_parse_safe(lhs), _parse_safe(rhs)), symbol)
        return [str(item) for item in result]
    except Exception:
        return []

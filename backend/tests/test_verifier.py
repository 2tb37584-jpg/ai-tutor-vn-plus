from app.services.verifier import equivalent, solve_simple_equation


def test_equivalent_expressions():
    assert equivalent("(x+1)*(x+1)", "x^2+2*x+1")


def test_rejects_unsafe_characters():
    assert not equivalent("__import__('os')", "0")


def test_solve_linear_equation():
    assert solve_simple_equation("2*x+3=7") == ["2"]

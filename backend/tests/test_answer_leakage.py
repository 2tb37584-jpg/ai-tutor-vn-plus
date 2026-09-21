import pytest

from app.services.answer_leakage import detects_final_answer_leak


@pytest.mark.parametrize(
    ("message", "expected_answer", "model_reports_reveal", "detected"),
    [
        ("A small hint", "2", True, True),
        ("Try adding to both sides", "x = 2", False, False),
        ("Any message", "", False, False),
        ("Any message", "   ", True, True),
        ("Vậy x=2.", "x = 2", False, True),
        ("VẬY  X =   2.", "x=2", False, True),
        ("Đáp án là Hà Nội.", "Ha\u0300 Nô\u0323i", False, True),
        ("Hãy thử cộng 2 vào hai vế.", "2", False, False),
        ("Đáp án là 2.", "2", False, True),
        ("Vậy x = 2.", "2", False, True),
        ("Ta có 20 học sinh.", "2", False, False),
    ],
)
def test_detects_final_answer_leak(
    message: str,
    expected_answer: str,
    model_reports_reveal: bool,
    detected: bool,
) -> None:
    assert detects_final_answer_leak(message, expected_answer, model_reports_reveal) is detected


@pytest.mark.parametrize(
    ("message", "expected_answer"),
    [
        ("đáp án là 4", "4"),
        ("kết quả là 4", "4"),
        ("answer is 4", "4"),
        ("result = 4", "4"),
        ("x = 4", "4"),
        ("x=4", "4"),
        ("y = -2", "-2"),
        ("Đáp án là -2", "-2"),
        ("Answer is 2.5", "2.5"),
        ("Kết quả là 2,5", "2,5"),
        ("Đáp án là (x-2)(x-3)", "(x-2)(x-3)"),
        ("Điều kiện là x != 2", "x != 2"),
    ],
)
def test_direct_answer_forms_are_detected(message: str, expected_answer: str) -> None:
    assert detects_final_answer_leak(message, expected_answer, False) is True


def test_model_self_report_detects_safe_looking_text() -> None:
    assert detects_final_answer_leak("Em hãy thử bước đầu tiên.", "4", True) is True


def test_nfkc_case_and_whitespace_are_normalized() -> None:
    assert detects_final_answer_leak("ＡＮＳＷＥＲ　ＩＳ   ４", "4", False) is True
    assert detects_final_answer_leak("VẬY   X   =   4", "4", False) is True


@pytest.mark.parametrize("message", ["Có 40 học sinh.", "Hạng tử 4x."])
def test_scalar_boundaries_avoid_false_positives(message: str) -> None:
    assert detects_final_answer_leak(message, "4", False) is False


def test_instructional_use_of_answer_number_is_safe() -> None:
    assert detects_final_answer_leak("Hãy thử cộng 2 vào hai vế.", "2", False) is False


@pytest.mark.parametrize(
    "message",
    [
        "Hãy gom các hạng tử chứa x.",
        "Trong 2x + 5 - x - 5, những hạng tử nào cùng loại?",
        "Em hãy quan sát hệ số của x.",
    ],
)
def test_instructional_single_symbol_references_are_safe(message: str) -> None:
    assert detects_final_answer_leak(message, "x", False) is False


@pytest.mark.parametrize(
    "message",
    [
        "Đáp án là x.",
        "Kết quả là x.",
        "Answer is x.",
        "Result = x.",
        "x",
        "x.",
        "(x)",
    ],
)
def test_direct_single_symbol_disclosures_are_detected(message: str) -> None:
    assert detects_final_answer_leak(message, "x", False) is True


def test_single_symbol_model_self_report_remains_an_unconditional_leak() -> None:
    assert detects_final_answer_leak("Hãy gom các hạng tử chứa x.", "x", True) is True


def test_decimal_point_and_comma_are_not_treated_as_equivalent() -> None:
    assert detects_final_answer_leak("Đáp án là 2,5", "2.5", False) is False
    assert detects_final_answer_leak("Đáp án là 2.5", "2,5", False) is False

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

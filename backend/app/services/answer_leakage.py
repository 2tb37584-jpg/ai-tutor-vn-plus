"""Deterministic detection of direct final-answer disclosure."""

import re
import unicodedata


_NUMERIC_SCALAR = re.compile(r"[+-]?\d+(?:[.,]\d+)?\Z")
_SINGLE_SYMBOL = re.compile(r"[a-z]\Z")
_ANSWER_CUE = r"(?:đáp án|kết quả|answer|result)\s*(?:là|is|:|=)?\s*"
_ASSIGNMENT = r"\b[a-z]\s*=\s*"


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold()
    text = " ".join(text.split())
    return re.sub(r"\s*=\s*", "=", text)


def detects_final_answer_leak(
    message: str,
    expected_answer: str,
    model_reports_reveal: bool,
) -> bool:
    """Detect a model self-report or a direct textual answer disclosure."""
    if model_reports_reveal:
        return True

    answer = _normalize(expected_answer)
    if not answer:
        return False

    text = _normalize(message)
    bounded_answer = rf"(?<!\w){re.escape(answer)}(?!\w)"
    if _NUMERIC_SCALAR.fullmatch(answer):
        return bool(
            re.search(_ANSWER_CUE + bounded_answer, text)
            or re.search(_ASSIGNMENT + bounded_answer, text)
        )

    if _SINGLE_SYMBOL.fullmatch(answer):
        return bool(
            re.search(_ANSWER_CUE + bounded_answer, text)
            or re.fullmatch(rf"[\s().,!?;:]*{re.escape(answer)}[\s().,!?;:]*", text)
        )

    return re.search(bounded_answer, text) is not None

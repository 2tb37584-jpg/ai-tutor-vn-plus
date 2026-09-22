import pytest

from app.services.verification_policy import (
    EffectiveCorrectness,
    EscalationAction,
    resolve_verification_decision,
)
from app.services.verifier import VerificationStatus


@pytest.mark.parametrize(
    ("model_likely_correct", "disagreement"),
    [(True, False), (False, True), (None, False)],
)
def test_correct_is_authoritative(
    model_likely_correct: bool | None,
    disagreement: bool,
) -> None:
    decision = resolve_verification_decision(
        VerificationStatus.CORRECT,
        model_likely_correct,
    )

    assert decision.correctness is EffectiveCorrectness.CORRECT
    assert decision.action is EscalationAction.ACCEPT_DETERMINISTIC
    assert decision.mastery_eligible is True
    assert decision.disagreement is disagreement
    assert decision.retry_allowed is False


@pytest.mark.parametrize(
    ("model_likely_correct", "disagreement"),
    [(True, True), (False, False), (None, False)],
)
def test_incorrect_is_authoritative(
    model_likely_correct: bool | None,
    disagreement: bool,
) -> None:
    decision = resolve_verification_decision(
        VerificationStatus.INCORRECT,
        model_likely_correct,
    )

    assert decision.correctness is EffectiveCorrectness.INCORRECT
    assert decision.action is EscalationAction.ACCEPT_DETERMINISTIC
    assert decision.mastery_eligible is True
    assert decision.disagreement is disagreement
    assert decision.retry_allowed is False


@pytest.mark.parametrize("model_likely_correct", [True, False, None])
def test_unsupported_uses_model_assistance_without_mastery(
    model_likely_correct: bool | None,
) -> None:
    decision = resolve_verification_decision(
        VerificationStatus.UNSUPPORTED,
        model_likely_correct,
    )

    assert decision.correctness is EffectiveCorrectness.UNKNOWN
    assert decision.action is EscalationAction.MODEL_ASSISTED_ONLY
    assert decision.mastery_eligible is False
    assert decision.disagreement is False
    assert decision.retry_allowed is False


@pytest.mark.parametrize(
    ("retry_count", "action", "retry_allowed"),
    [
        (0, EscalationAction.RETRY_DETERMINISTIC, True),
        (1, EscalationAction.MODEL_ASSISTED_ONLY, False),
        (2, EscalationAction.MODEL_ASSISTED_ONLY, False),
    ],
)
@pytest.mark.parametrize("model_likely_correct", [True, False, None])
def test_indeterminate_allows_exactly_one_retry(
    retry_count: int,
    action: EscalationAction,
    retry_allowed: bool,
    model_likely_correct: bool | None,
) -> None:
    decision = resolve_verification_decision(
        VerificationStatus.INDETERMINATE,
        model_likely_correct=model_likely_correct,
        retry_count=retry_count,
    )

    assert decision.correctness is EffectiveCorrectness.UNKNOWN
    assert decision.action is action
    assert decision.mastery_eligible is False
    assert decision.disagreement is False
    assert decision.retry_allowed is retry_allowed


def test_negative_retry_count_is_rejected() -> None:
    with pytest.raises(ValueError, match="retry_count"):
        resolve_verification_decision(
            VerificationStatus.INDETERMINATE,
            model_likely_correct=None,
            retry_count=-1,
        )

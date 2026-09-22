from dataclasses import dataclass
from enum import Enum

from app.services.verifier import VerificationStatus


class EffectiveCorrectness(str, Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    UNKNOWN = "unknown"


class EscalationAction(str, Enum):
    ACCEPT_DETERMINISTIC = "accept_deterministic"
    RETRY_DETERMINISTIC = "retry_deterministic"
    MODEL_ASSISTED_ONLY = "model_assisted_only"


@dataclass(frozen=True)
class VerificationDecision:
    correctness: EffectiveCorrectness
    action: EscalationAction
    mastery_eligible: bool
    disagreement: bool
    retry_allowed: bool


def resolve_verification_decision(
    verifier_status: VerificationStatus,
    model_likely_correct: bool | None,
    retry_count: int = 0,
) -> VerificationDecision:
    if retry_count < 0:
        raise ValueError("retry_count must not be negative")

    if verifier_status is VerificationStatus.CORRECT:
        return VerificationDecision(
            correctness=EffectiveCorrectness.CORRECT,
            action=EscalationAction.ACCEPT_DETERMINISTIC,
            mastery_eligible=True,
            disagreement=model_likely_correct is False,
            retry_allowed=False,
        )

    if verifier_status is VerificationStatus.INCORRECT:
        return VerificationDecision(
            correctness=EffectiveCorrectness.INCORRECT,
            action=EscalationAction.ACCEPT_DETERMINISTIC,
            mastery_eligible=True,
            disagreement=model_likely_correct is True,
            retry_allowed=False,
        )

    if verifier_status is VerificationStatus.UNSUPPORTED:
        return VerificationDecision(
            correctness=EffectiveCorrectness.UNKNOWN,
            action=EscalationAction.MODEL_ASSISTED_ONLY,
            mastery_eligible=False,
            disagreement=False,
            retry_allowed=False,
        )

    if verifier_status is VerificationStatus.INDETERMINATE:
        return VerificationDecision(
            correctness=EffectiveCorrectness.UNKNOWN,
            action=(
                EscalationAction.RETRY_DETERMINISTIC
                if retry_count == 0
                else EscalationAction.MODEL_ASSISTED_ONLY
            ),
            mastery_eligible=False,
            disagreement=False,
            retry_allowed=retry_count == 0,
        )

    raise ValueError("Unknown verifier status")

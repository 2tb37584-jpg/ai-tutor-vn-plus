"""Deterministic tutor progression rules.

This module deliberately has no model, API, or database dependencies.
"""

from app.schemas.tutor import TutorState, TutorTransitionEvent, TutorTransitionInput


class InvalidTutorTransition(ValueError):
    """Raised when an event is not valid for the current tutor state."""


_TRANSITIONS: dict[tuple[TutorState, TutorTransitionEvent], TutorState] = {
    (TutorState.DIAGNOSE, TutorTransitionEvent.ANALYSIS_READY): TutorState.ASK_ATTEMPT,
    (TutorState.ASK_ATTEMPT, TutorTransitionEvent.ATTEMPT_CORRECT): TutorState.VERIFY,
    (TutorState.ASK_ATTEMPT, TutorTransitionEvent.ATTEMPT_INCORRECT): TutorState.HINT_1,
    (TutorState.HINT_1, TutorTransitionEvent.ATTEMPT_CORRECT): TutorState.VERIFY,
    (TutorState.HINT_1, TutorTransitionEvent.ATTEMPT_INCORRECT): TutorState.HINT_2,
    (TutorState.HINT_2, TutorTransitionEvent.ATTEMPT_CORRECT): TutorState.VERIFY,
    (TutorState.HINT_2, TutorTransitionEvent.ATTEMPT_INCORRECT): TutorState.EXPLAIN_STEP,
    (TutorState.ASK_ATTEMPT, TutorTransitionEvent.HINT_REQUESTED): TutorState.HINT_1,
    (TutorState.HINT_1, TutorTransitionEvent.HINT_REQUESTED): TutorState.HINT_2,
    (TutorState.HINT_2, TutorTransitionEvent.HINT_REQUESTED): TutorState.EXPLAIN_STEP,
    (TutorState.EXPLAIN_STEP, TutorTransitionEvent.STEP_EXPLAINED): TutorState.VERIFY,
    (TutorState.VERIFY, TutorTransitionEvent.VERIFIED): TutorState.TRANSFER,
    (TutorState.VERIFY, TutorTransitionEvent.VERIFICATION_FAILED): TutorState.EXPLAIN_STEP,
    (TutorState.TRANSFER, TutorTransitionEvent.TRANSFER_COMPLETED): TutorState.COMPLETE,
}


def transition_tutor_state(transition: TutorTransitionInput) -> TutorState:
    """Return the next state for a valid transition or fail explicitly."""
    try:
        return _TRANSITIONS[(transition.state, transition.event)]
    except KeyError as error:
        raise InvalidTutorTransition(
            f"Event {transition.event.value!r} is not allowed from state {transition.state.value!r}."
        ) from error

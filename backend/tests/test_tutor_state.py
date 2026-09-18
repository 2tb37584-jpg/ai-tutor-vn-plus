import pytest

from app.schemas.tutor import TutorState, TutorTransitionEvent, TutorTransitionInput
from app.services.tutor_state import InvalidTutorTransition, transition_tutor_state


def test_happy_path_progression_reaches_complete() -> None:
    transitions = [
        TutorTransitionEvent.ANALYSIS_READY,
        TutorTransitionEvent.ATTEMPT_CORRECT,
        TutorTransitionEvent.VERIFIED,
        TutorTransitionEvent.TRANSFER_COMPLETED,
    ]
    state = TutorState.DIAGNOSE

    for event in transitions:
        state = transition_tutor_state(TutorTransitionInput(state=state, event=event))

    assert state is TutorState.COMPLETE


def test_wrong_attempts_escalate_through_hints_to_explanation() -> None:
    state = TutorState.ASK_ATTEMPT

    state = transition_tutor_state(
        TutorTransitionInput(state=state, event=TutorTransitionEvent.ATTEMPT_INCORRECT)
    )
    assert state is TutorState.HINT_1

    state = transition_tutor_state(
        TutorTransitionInput(state=state, event=TutorTransitionEvent.ATTEMPT_INCORRECT)
    )
    assert state is TutorState.HINT_2

    state = transition_tutor_state(
        TutorTransitionInput(state=state, event=TutorTransitionEvent.ATTEMPT_INCORRECT)
    )
    assert state is TutorState.EXPLAIN_STEP


def test_impossible_transition_fails_explicitly() -> None:
    transition = TutorTransitionInput(
        state=TutorState.DIAGNOSE,
        event=TutorTransitionEvent.VERIFIED,
    )

    with pytest.raises(InvalidTutorTransition, match="not allowed"):
        transition_tutor_state(transition)


def test_unknown_event_is_rejected_by_typed_input() -> None:
    with pytest.raises(ValueError):
        TutorTransitionInput(state=TutorState.DIAGNOSE, event="unknown")

from types import SimpleNamespace

from app.schemas.tutor import ProblemAnalysis, TutorState, TutorTurn
from app.services.tutor_ai import TutorAI


def demo_tutor() -> TutorAI:
    tutor = TutorAI.__new__(TutorAI)
    tutor.client = None
    return tutor


def analysis() -> ProblemAnalysis:
    return ProblemAnalysis(normalized_problem="Solve x + 1 = 2")


def test_first_turn_produces_ask_attempt() -> None:
    turn = demo_tutor().first_turn(analysis(), grade=6)

    assert turn.state is TutorState.ASK_ATTEMPT


def test_incorrect_attempt_from_ask_attempt_produces_hint_1() -> None:
    turn = TutorTurn(message="Try again", likely_correct=False)

    result = TutorAI._with_continued_turn_state(turn, TutorState.ASK_ATTEMPT)

    assert result.state is TutorState.HINT_1


def test_incorrect_attempt_from_hint_1_produces_hint_2() -> None:
    turn = TutorTurn(message="Try again", likely_correct=False)

    result = TutorAI._with_continued_turn_state(turn, TutorState.HINT_1)

    assert result.state is TutorState.HINT_2


def test_incorrect_attempt_from_hint_2_produces_explain_step() -> None:
    turn = TutorTurn(message="Try again", likely_correct=False)

    result = TutorAI._with_continued_turn_state(turn, TutorState.HINT_2)

    assert result.state is TutorState.EXPLAIN_STEP


def test_correct_attempt_produces_verify() -> None:
    turn = TutorTurn(message="Correct", likely_correct=True)

    result = TutorAI._with_continued_turn_state(turn, TutorState.HINT_2)

    assert result.state is TutorState.VERIFY


def test_missing_correctness_signal_retains_current_state() -> None:
    turn = TutorTurn(message="Explain your reasoning", likely_correct=None)

    result = TutorAI._with_continued_turn_state(turn, TutorState.HINT_1)

    assert result.state is TutorState.HINT_1


def test_non_attempt_states_retain_state_despite_correctness_signal() -> None:
    non_attempt_states = (
        TutorState.EXPLAIN_STEP,
        TutorState.VERIFY,
        TutorState.TRANSFER,
        TutorState.COMPLETE,
    )

    for current_state in non_attempt_states:
        for likely_correct in (True, False):
            turn = TutorTurn(message="Continue", likely_correct=likely_correct)

            result = TutorAI._with_continued_turn_state(turn, current_state)

            assert result.state is current_state


def test_model_provided_state_is_overwritten_by_application_state() -> None:
    raw_turn = TutorTurn(message="Try", likely_correct=False, state=TutorState.COMPLETE)
    tutor = TutorAI.__new__(TutorAI)
    tutor.settings = SimpleNamespace(openai_model="test-model")
    tutor.client = SimpleNamespace(
        responses=SimpleNamespace(parse=lambda **_: SimpleNamespace(output_parsed=raw_turn))
    )

    result = tutor.continue_turn("problem", "skill", [], "attempt", current_state=TutorState.ASK_ATTEMPT)

    assert result.state is TutorState.HINT_1


def test_continue_turn_existing_call_shape_uses_default_state() -> None:
    result = demo_tutor().continue_turn("problem", "skill", [], "attempt")

    assert result.state is TutorState.ASK_ATTEMPT

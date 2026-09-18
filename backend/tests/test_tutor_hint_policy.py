from types import SimpleNamespace

from app.schemas.tutor import TutorState, TutorTurn
from app.services.tutor_ai import TutorAI


def demo_tutor() -> TutorAI:
    tutor = TutorAI.__new__(TutorAI)
    tutor.client = None
    return tutor


def test_ask_attempt_policy_is_first_level_and_leaves_work() -> None:
    policy = TutorAI._generation_policy(TutorState.ASK_ATTEMPT)

    assert "first-level" in policy
    assert "one small conceptual cue" in policy
    assert "Do not perform" in policy


def test_hint_1_policy_is_more_concrete_than_ask_attempt() -> None:
    policy = TutorAI._generation_policy(TutorState.HINT_1)

    assert "stronger, more concrete scaffold" in policy
    assert "operation, relation, formula, or sub-step" in policy


def test_hint_2_policy_allows_one_step_without_a_complete_solution() -> None:
    policy = TutorAI._generation_policy(TutorState.HINT_2)

    assert "exactly one useful intermediate step" in policy
    assert "Stop after that step" in policy
    assert "Do not provide a complete worked solution" in policy


def test_explain_step_policy_focuses_on_applying_the_existing_step() -> None:
    policy = TutorAI._generation_policy(TutorState.EXPLAIN_STEP)

    assert "apply or justify" in policy
    assert "Do not add further worked steps" in policy


def test_resulting_states_control_hint_levels() -> None:
    assert TutorAI._with_continued_turn_state(
        TutorTurn(message="Try", likely_correct=False, hint_level=5), TutorState.ASK_ATTEMPT
    ).hint_level == 1
    assert TutorAI._with_continued_turn_state(
        TutorTurn(message="Try", likely_correct=False, hint_level=0), TutorState.HINT_1
    ).hint_level == 2
    assert TutorAI._with_continued_turn_state(
        TutorTurn(message="Try", likely_correct=False, hint_level=0), TutorState.HINT_2
    ).hint_level == 3


def test_model_state_and_hint_level_are_overwritten_by_application_metadata() -> None:
    raw_turn = TutorTurn(
        message="Try",
        state=TutorState.COMPLETE,
        hint_level=5,
        likely_correct=False,
    )

    result = TutorAI._with_continued_turn_state(raw_turn, TutorState.HINT_1)

    assert result.state is TutorState.HINT_2
    assert result.hint_level == 2


def test_continue_turn_prompt_includes_current_state_policy() -> None:
    captured: dict[str, object] = {}
    raw_turn = TutorTurn(message="Try", likely_correct=None)
    tutor = TutorAI.__new__(TutorAI)
    tutor.settings = SimpleNamespace(openai_model="test-model")
    tutor.client = SimpleNamespace(
        responses=SimpleNamespace(
            parse=lambda **kwargs: captured.update(kwargs) or SimpleNamespace(output_parsed=raw_turn)
        )
    )

    tutor.continue_turn("problem", "skill", [], "attempt", current_state=TutorState.HINT_2)

    user_prompt = captured["input"][1]["content"]
    assert "Current tutor state: hint_2" in user_prompt
    assert "First judge the student's newest attempt" in user_prompt
    assert "clearly correct, set likely_correct=True" in user_prompt
    assert "do not escalate the hint or explain another solution step" in user_prompt
    assert "ask the student to verify or check it" in user_prompt
    assert "clearly incorrect, set likely_correct=False" in user_prompt
    assert "follow the current-state assistance policy below" in user_prompt
    assert "only for a clearly incorrect attempt" in user_prompt
    assert "exactly one useful intermediate step" in user_prompt
    assert "cannot reasonably be judged, set likely_correct=None" in user_prompt
    assert "ask one focused clarification question and do not escalate assistance" in user_prompt


def test_non_attempt_prompt_uses_only_its_current_state_policy() -> None:
    captured: dict[str, object] = {}
    tutor = TutorAI.__new__(TutorAI)
    tutor.settings = SimpleNamespace(openai_model="test-model")
    tutor.client = SimpleNamespace(
        responses=SimpleNamespace(
            parse=lambda **kwargs: captured.update(kwargs)
            or SimpleNamespace(output_parsed=TutorTurn(message="Continue"))
        )
    )

    tutor.continue_turn("problem", "skill", [], "attempt", current_state=TutorState.EXPLAIN_STEP)

    user_prompt = captured["input"][1]["content"]
    assert "Current tutor state: explain_step" in user_prompt
    assert "Current-state generation policy:" in user_prompt
    assert "ask the student to apply or justify it" in user_prompt
    assert "Attempt response policy:" not in user_prompt
    assert "likely_correct=True" not in user_prompt
    assert "likely_correct=False" not in user_prompt
    assert "likely_correct=None" not in user_prompt


def test_demo_mode_normalizes_state_and_hint_level() -> None:
    result = demo_tutor().continue_turn("problem", "skill", [], "attempt", current_state=TutorState.HINT_2)

    assert result.state is TutorState.HINT_2
    assert result.hint_level == 2


def test_continue_turn_existing_call_shape_remains_compatible() -> None:
    result = demo_tutor().continue_turn("problem", "skill", [], "attempt")

    assert result.state is TutorState.ASK_ATTEMPT
    assert result.hint_level == 0

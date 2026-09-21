from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.tutor import ProblemAnalysis, TutorState, TutorTurn
from app.services import tutor_ai


class ParseRecorder:
    def __init__(self, parsed, *, output_style: str):
        self.calls = []
        self.parsed = parsed
        self.output_style = output_style

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.output_style == "responses":
            return SimpleNamespace(output_parsed=self.parsed)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=self.parsed))]
        )


def _tutor(mode: str, *, responses_parsed=None, chat_parsed=None):
    responses = ParseRecorder(responses_parsed, output_style="responses")
    chat_completions = ParseRecorder(chat_parsed, output_style="chat")
    tutor = tutor_ai.TutorAI.__new__(tutor_ai.TutorAI)
    tutor.settings = SimpleNamespace(
        openai_api_mode=mode,
        openai_model="test-model",
    )
    tutor.client = SimpleNamespace(
        responses=responses,
        chat=SimpleNamespace(completions=chat_completions),
    )
    return tutor, responses, chat_completions


def _analysis() -> ProblemAnalysis:
    return ProblemAnalysis(normalized_problem="Solve x + 1 = 2")


def test_default_api_mode_is_responses(monkeypatch):
    monkeypatch.delenv("OPENAI_API_MODE", raising=False)

    assert Settings(_env_file=None).openai_api_mode == "responses"


def test_invalid_api_mode_is_rejected_by_settings(monkeypatch):
    monkeypatch.setenv("OPENAI_API_MODE", "unsupported")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_responses_mode_returns_responses_parsed_output():
    expected = _analysis()
    tutor, responses, chat_completions = _tutor("responses", responses_parsed=expected)

    result = tutor.analyze_problem("Solve x + 1 = 2")

    assert result is expected
    assert isinstance(result, ProblemAnalysis)
    assert len(responses.calls) == 1
    assert chat_completions.calls == []


def test_chat_completions_mode_returns_parsed_problem_analysis():
    expected = _analysis()
    tutor, responses, chat_completions = _tutor("chat_completions", chat_parsed=expected)

    result = tutor.analyze_problem("Solve x + 1 = 2")

    assert result is expected
    assert isinstance(result, ProblemAnalysis)
    assert responses.calls == []
    assert len(chat_completions.calls) == 1
    assert chat_completions.calls[0]["response_format"] is ProblemAnalysis
    assert chat_completions.calls[0]["messages"][1]["content"] == [
        {"type": "text", "text": "Solve x + 1 = 2"}
    ]


def test_unsupported_api_mode_fails_without_fallback():
    tutor, responses, chat_completions = _tutor("unsupported")

    with pytest.raises(ValueError, match="Unsupported OpenAI API mode"):
        tutor.analyze_problem("Solve x + 1 = 2")

    assert responses.calls == []
    assert chat_completions.calls == []


def test_first_turn_preserves_prompt_content_across_modes():
    analysis = ProblemAnalysis(
        normalized_problem="Solve x + 1 = 2",
        skills=["algebra.linear_equation"],
        prerequisites=["arithmetic"],
    )
    responses_tutor, responses, _ = _tutor(
        "responses",
        responses_parsed=TutorTurn(message="Try a step", state=TutorState.COMPLETE),
    )
    chat_tutor, _, chat_completions = _tutor(
        "chat_completions",
        chat_parsed=TutorTurn(message="Try a step", state=TutorState.COMPLETE),
    )

    responses_result = responses_tutor.first_turn(analysis, grade=8)
    chat_result = chat_tutor.first_turn(analysis, grade=8)

    responses_input = responses.calls[0]["input"]
    chat_messages = chat_completions.calls[0]["messages"]
    assert responses_input == chat_messages
    assert responses_result.state is TutorState.ASK_ATTEMPT
    assert chat_result.state is TutorState.ASK_ATTEMPT
    assert isinstance(chat_result, TutorTurn)


def test_continue_turn_preserves_prompt_content_and_state_normalization():
    raw_turn = TutorTurn(
        message="Try again",
        likely_correct=False,
        state=TutorState.COMPLETE,
    )
    responses_tutor, responses, _ = _tutor("responses", responses_parsed=raw_turn)
    chat_tutor, _, chat_completions = _tutor("chat_completions", chat_parsed=raw_turn)
    args = ("problem", "skill", [("student", "attempt")], "attempt")

    responses_result = responses_tutor.continue_turn(*args)
    chat_result = chat_tutor.continue_turn(*args)

    assert responses.calls[0]["input"] == chat_completions.calls[0]["messages"]
    assert responses_result.state is TutorState.HINT_1
    assert chat_result.state is TutorState.HINT_1
    assert isinstance(chat_result, TutorTurn)


def test_chat_completions_image_transport_preserves_text_url_and_detail():
    image_data_url = "data:image/png;base64,example"
    tutor, _, chat_completions = _tutor(
        "chat_completions",
        chat_parsed=_analysis(),
    )

    tutor.analyze_problem("Read this image", image_data_url=image_data_url)

    content = chat_completions.calls[0]["messages"][1]["content"]
    assert content == [
        {"type": "text", "text": "Read this image"},
        {
            "type": "image_url",
            "image_url": {"url": image_data_url, "detail": "auto"},
        },
    ]


def test_responses_image_transport_remains_unchanged():
    image_data_url = "data:image/png;base64,example"
    tutor, responses, _ = _tutor("responses", responses_parsed=_analysis())

    tutor.analyze_problem("Read this image", image_data_url=image_data_url)

    assert responses.calls[0]["input"][1]["content"] == [
        {"type": "input_text", "text": "Read this image"},
        {"type": "input_image", "image_url": image_data_url, "detail": "auto"},
    ]


def test_missing_chat_completions_parsed_output_fails_explicitly():
    tutor, _, _ = _tutor("chat_completions", chat_parsed=None)

    with pytest.raises(RuntimeError, match="did not include parsed output"):
        tutor.first_turn(_analysis(), grade=8)


def test_custom_base_url_construction_remains_unchanged(monkeypatch):
    calls = []

    class FakeOpenAI:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    settings = SimpleNamespace(
        openai_api_key="test-key",
        openai_base_url="  https://provider.example/v1  ",
        openai_api_mode="chat_completions",
        openai_model="test-model",
    )
    monkeypatch.setattr(tutor_ai, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(tutor_ai, "get_settings", lambda: settings)

    tutor_ai.TutorAI()

    assert calls == [
        {
            "api_key": "test-key",
            "base_url": "https://provider.example/v1",
        }
    ]

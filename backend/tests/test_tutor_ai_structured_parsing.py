from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.tutor import ProblemAnalysis
from app.services import tutor_ai


class CreateRecorder:
    def __init__(self, content: object) -> None:
        self.calls: list[dict] = []
        self.content = content

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


class ResponsesRecorder:
    def __init__(self, parsed: ProblemAnalysis | None = None) -> None:
        self.calls: list[dict] = []
        self.parsed = parsed

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_parsed=self.parsed)


def _tutor(mode: str, *, content: object = None, responses_parsed=None):
    completions = CreateRecorder(content)
    responses = ResponsesRecorder(responses_parsed)
    instance = tutor_ai.TutorAI.__new__(tutor_ai.TutorAI)
    instance.settings = SimpleNamespace(
        openai_api_mode=mode,
        openai_model="test-model",
    )
    instance.client = SimpleNamespace(
        responses=responses,
        chat=SimpleNamespace(completions=completions),
    )
    return instance, responses, completions


def _analysis_json() -> str:
    return ProblemAnalysis(
        normalized_problem="Solve x + 1 = 2",
        skills=["algebra.linear_equation"],
        confidence=0.9,
    ).model_dump_json()


def test_chat_completions_raw_json_uses_one_structured_request():
    instance, responses, completions = _tutor("chat_completions", content=_analysis_json())

    result = instance.analyze_problem("Solve x + 1 = 2")

    assert result.normalized_problem == "Solve x + 1 = 2"
    assert result.skills == ["algebra.linear_equation"]
    assert responses.calls == []
    assert len(completions.calls) == 1
    response_format = completions.calls[0]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "ProblemAnalysis"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["schema"]["additionalProperties"] is False


@pytest.mark.parametrize(
    "content",
    [
        "```json\n" + _analysis_json() + "\n```",
        "```\n" + _analysis_json() + "\n```",
        "  \n```JSON\n" + _analysis_json() + "\n```\n  ",
    ],
)
def test_chat_completions_accepts_one_complete_outer_json_fence(content: str):
    instance, _, completions = _tutor("chat_completions", content=content)

    result = instance.analyze_problem("Solve x + 1 = 2")

    assert result.normalized_problem == "Solve x + 1 = 2"
    assert len(completions.calls) == 1


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "Here is the result:\n" + _analysis_json(),
        "```json\n" + _analysis_json() + "\n```\nExtra explanation",
        '{"subject":"math"}',
    ],
)
def test_chat_completions_invalid_or_untrusted_content_fails_closed(content: str):
    instance, _, completions = _tutor("chat_completions", content=content)

    with pytest.raises(ValidationError):
        instance.analyze_problem("Solve x + 1 = 2")

    assert len(completions.calls) == 1


@pytest.mark.parametrize("content", [None, "", "   "])
def test_chat_completions_empty_content_fails_closed(content: object):
    instance, _, completions = _tutor("chat_completions", content=content)

    with pytest.raises(RuntimeError, match="did not include structured content"):
        instance.analyze_problem("Solve x + 1 = 2")

    assert len(completions.calls) == 1


def test_responses_mode_remains_on_sdk_parse_path():
    expected = ProblemAnalysis(normalized_problem="Solve x + 1 = 2")
    instance, responses, completions = _tutor("responses", responses_parsed=expected)

    result = instance.analyze_problem("Solve x + 1 = 2")

    assert result is expected
    assert len(responses.calls) == 1
    assert completions.calls == []

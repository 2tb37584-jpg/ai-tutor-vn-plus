from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.tutor import ProblemAnalysis, TutorState, TutorTurn
from app.services import tutor_ai


class RawResponse:
    def __init__(self, body: object) -> None:
        self.body = body

    def json(self) -> object:
        return self.body


class RawParseRecorder:
    def __init__(self, body: object) -> None:
        self.calls: list[dict] = []
        self.body = body

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return RawResponse(self.body)


class ResponsesRecorder:
    def __init__(self, parsed: ProblemAnalysis | None = None) -> None:
        self.calls: list[dict] = []
        self.parsed = parsed

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_parsed=self.parsed)


_MISSING = object()


def _tutor(
    mode: str,
    *,
    content: object = _MISSING,
    response_body: object = _MISSING,
    responses_parsed=None,
):
    if response_body is _MISSING:
        if content is _MISSING:
            response_body = {}
        else:
            response_body = {"choices": [{"message": {"content": content}}]}

    raw_parse = RawParseRecorder(response_body)
    responses = ResponsesRecorder(responses_parsed)
    completions = SimpleNamespace(
        with_raw_response=SimpleNamespace(parse=raw_parse.parse),
    )
    instance = tutor_ai.TutorAI.__new__(tutor_ai.TutorAI)
    instance.settings = SimpleNamespace(
        openai_api_mode=mode,
        openai_model="test-model",
    )
    instance.client = SimpleNamespace(
        responses=responses,
        chat=SimpleNamespace(completions=completions),
    )
    return instance, responses, raw_parse


def _analysis_json() -> str:
    return ProblemAnalysis(
        normalized_problem="Solve x + 1 = 2",
        skills=["algebra.linear_equation"],
        confidence=0.9,
    ).model_dump_json()


def _run_analysis(instance: tutor_ai.TutorAI) -> ProblemAnalysis:
    return instance.analyze_problem("Solve x + 1 = 2")


def test_chat_completions_raw_json_uses_one_public_structured_request():
    instance, responses, raw_parse = _tutor("chat_completions", content=_analysis_json())

    result = _run_analysis(instance)

    assert result.normalized_problem == "Solve x + 1 = 2"
    assert result.skills == ["algebra.linear_equation"]
    assert responses.calls == []
    assert len(raw_parse.calls) == 1
    assert raw_parse.calls[0]["response_format"] is ProblemAnalysis
    assert raw_parse.calls[0]["model"] == "test-model"


@pytest.mark.parametrize(
    "content",
    [
        "```json\n" + _analysis_json() + "\n```",
        "```\n" + _analysis_json() + "\n```",
        "  \n```JSON\n" + _analysis_json() + "\n```\n  ",
    ],
)
def test_chat_completions_accepts_one_complete_outer_json_fence(content: str):
    instance, _, raw_parse = _tutor("chat_completions", content=content)

    result = _run_analysis(instance)

    assert result.normalized_problem == "Solve x + 1 = 2"
    assert len(raw_parse.calls) == 1


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "Here is the result:\n" + _analysis_json(),
        "```json\n" + _analysis_json() + "\n```\nExtra explanation",
        "```json\n" + _analysis_json() + "\n",
        "```json " + _analysis_json() + " ```",
        '{"subject":"math"}',
    ],
)
def test_chat_completions_invalid_or_untrusted_content_fails_closed(content: str):
    instance, _, raw_parse = _tutor("chat_completions", content=content)

    with pytest.raises(ValidationError):
        _run_analysis(instance)

    assert len(raw_parse.calls) == 1


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": None}}]},
        {"choices": [{"message": {"content": ""}}]},
        {"choices": [{"message": {"content": "   "}}]},
    ],
)
def test_chat_completions_missing_or_empty_content_fails_closed(body: object):
    instance, _, raw_parse = _tutor("chat_completions", response_body=body)

    with pytest.raises(RuntimeError, match="Chat Completions response did not include"):
        _run_analysis(instance)

    assert len(raw_parse.calls) == 1


def test_fenced_tutor_turn_fields_are_validated_and_preserved():
    expected = TutorTurn(
        message="Hãy kiểm tra bước biến đổi tiếp theo.",
        state=TutorState.VERIFY,
        likely_correct=False,
        reveal_final_answer=True,
    )
    content = f"```json\n{expected.model_dump_json()}\n```"
    instance, responses, raw_parse = _tutor("chat_completions", content=content)

    result = instance._parse_structured(
        TutorTurn,
        responses_input=[],
        chat_messages=[],
    )

    assert result.message == expected.message
    assert result.state is TutorState.VERIFY
    assert result.likely_correct is False
    assert result.reveal_final_answer is True
    assert responses.calls == []
    assert len(raw_parse.calls) == 1
    assert raw_parse.calls[0]["response_format"] is TutorTurn


def test_responses_mode_remains_on_sdk_parse_path():
    expected = ProblemAnalysis(normalized_problem="Solve x + 1 = 2")
    instance, responses, raw_parse = _tutor("responses", responses_parsed=expected)

    result = _run_analysis(instance)

    assert result is expected
    assert len(responses.calls) == 1
    assert raw_parse.calls == []

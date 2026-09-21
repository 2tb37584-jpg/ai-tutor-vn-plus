from types import SimpleNamespace

from app.schemas.tutor import ProblemAnalysis
from app.services import tutor_ai
from app.services.skill_registry import get_controlled_skills


class ParseRecorder:
    def __init__(self, *, chat_completions: bool) -> None:
        self.calls: list[dict[str, object]] = []
        self.chat_completions = chat_completions

    def parse(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        parsed = ProblemAnalysis(normalized_problem="Solve x + 1 = 2")
        if self.chat_completions:
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))]
            )
        return SimpleNamespace(output_parsed=parsed)


def _tutor(mode: str) -> tuple[tutor_ai.TutorAI, ParseRecorder, ParseRecorder]:
    responses = ParseRecorder(chat_completions=False)
    chat_completions = ParseRecorder(chat_completions=True)
    tutor = tutor_ai.TutorAI.__new__(tutor_ai.TutorAI)
    tutor.settings = SimpleNamespace(openai_api_mode=mode, openai_model="test-model")
    tutor.client = SimpleNamespace(
        responses=responses,
        chat=SimpleNamespace(completions=chat_completions),
    )
    return tutor, responses, chat_completions


def _analysis_instruction(mode: str) -> str:
    tutor, responses, chat_completions = _tutor(mode)
    tutor.analyze_problem("Solve x + 1 = 2")
    if mode == "responses":
        return responses.calls[0]["input"][0]["content"]
    return chat_completions.calls[0]["messages"][0]["content"]


def test_responses_analysis_contract_contains_every_controlled_skill():
    instruction = _analysis_instruction("responses")

    for skill in get_controlled_skills():
        assert skill.code in instruction


def test_analysis_contract_restricts_skills_to_the_controlled_list():
    instruction = _analysis_instruction("responses")

    assert "use ONLY skill codes from the controlled list below" in instruction
    assert "Do not invent new skill codes, aliases, synonyms" in instruction
    assert "Choose the smallest directly relevant skill set" in instruction
    assert "`skills[0]` is the PRIMARY skill" in instruction
    assert "Choose exactly one primary skill" in instruction
    assert "main requested operation or pedagogical objective" in instruction
    assert "Put supporting or prerequisite skills after the primary" in instruction
    assert "explicit higher-level target skill" in instruction


def test_analysis_contract_orders_target_skills_before_prerequisites():
    instruction = _analysis_instruction("responses")

    assert "algebra.rational_expression.simplify first" in instruction
    assert "algebra.rational_expression.domain after it only if relevant" in instruction
    assert "algebra.expression.simplify first" in instruction
    assert "algebra.expression.distributive_property and algebra.expression.combine_like_terms" in instruction
    assert "algebra.identity.basic first" in instruction
    assert "must not replace the identity objective as primary" in instruction


def test_analysis_contract_distinguishes_simplifying_from_distributing():
    instruction = _analysis_instruction("responses")

    assert "simplify the whole non-rational algebraic expression" in instruction
    assert "algebra.expression.simplify remains primary even when distribution is a required step" in instruction
    assert "expand, distribute, or remove parentheses" in instruction
    assert "algebra.expression.distributive_property may be primary" in instruction


def test_invented_skill_codes_are_not_advertised_as_controlled_options():
    instruction = _analysis_instruction("responses")

    for skill_code in (
        "algebra.square_of_a_sum",
        "algebra.binomial_square",
        "algebra.simplify_expression",
        "algebra.rational_expressions",
    ):
        assert f"- {skill_code}" not in instruction


def test_existing_analysis_instructions_are_preserved():
    instruction = _analysis_instruction("responses")

    assert "Extract the exercise accurately" in instruction
    assert "Do not invent missing information" in instruction
    assert "expected answer is for internal verification" in instruction
    assert "ambiguous, lower confidence" in instruction


def test_chat_completions_receives_equivalent_analysis_contract():
    assert _analysis_instruction("responses") == _analysis_instruction("chat_completions")


def test_demo_mode_analysis_remains_unchanged():
    tutor = tutor_ai.TutorAI.__new__(tutor_ai.TutorAI)
    tutor.client = None

    analysis = tutor.analyze_problem("Solve x + 1 = 2")

    assert analysis.skills == ["general.problem_solving"]
    assert analysis.confidence == 0.2

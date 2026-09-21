from __future__ import annotations
from typing import Any, TypeVar

from openai import OpenAI
from app.core.config import get_settings
from app.schemas.tutor import (
    ProblemAnalysis,
    TutorReplyIntent,
    TutorState,
    TutorTransitionEvent,
    TutorTransitionInput,
    TutorTurn,
)
from app.services.tutor_state import transition_tutor_state

StructuredModel = TypeVar("StructuredModel", ProblemAnalysis, TutorTurn)

ANALYZE_PROMPT = """
You are the diagnostic layer of a Vietnamese tutoring system.
Extract the exercise accurately. Do not invent missing information.
Return structured fields only. Skill tags should be stable machine-readable slugs where possible,
for example: algebra.linear_equation, algebra.factorization, geometry.triangle_similarity.
The expected answer is for internal verification; it will not automatically be shown to the student.
If the image/text is ambiguous, lower confidence and explain the ambiguity in verification_notes.
""".strip()

TUTOR_PROMPT = """
You are a patient Vietnamese Socratic tutor.
Your job is to make the student think, not to complete homework for them.
Rules:
- Respond in Vietnamese unless the student's preferred language clearly differs.
- Start from the smallest useful next step.
- Ask one focused question at a time.
- Prefer hints over full solutions.
- Do not reveal the final answer early unless the student has already demonstrated the key reasoning,
  explicitly asks after meaningful effort, or the session is in review mode.
- If the student is wrong, identify the misconception without shaming them.
- Keep the message concise enough for a school student.
- Set likely_correct only when the student's last answer can reasonably be judged.
- `reveal_final_answer` must reflect whether your message actually reveals it.
""".strip()

_STATE_HINT_LEVELS = {
    TutorState.ASK_ATTEMPT: 0,
    TutorState.HINT_1: 1,
    TutorState.HINT_2: 2,
    TutorState.EXPLAIN_STEP: 3,
}

_ATTEMPT_STATES = frozenset({TutorState.ASK_ATTEMPT, TutorState.HINT_1, TutorState.HINT_2})

_ATTEMPT_RESPONSE_POLICY = (
    "First judge the student's newest attempt when it can reasonably be judged. "
    "If it is clearly correct, set likely_correct=True; do not escalate the hint or explain "
    "another solution step. Acknowledge the reasoning and ask the student to verify or check it. "
    "If it is clearly incorrect, set likely_correct=False and then follow the current-state "
    "assistance policy below. "
    "If correctness cannot reasonably be judged, set likely_correct=None; ask one focused "
    "clarification question and do not escalate assistance."
)

_STATE_GENERATION_POLICIES = {
    TutorState.ASK_ATTEMPT: (
        "Give first-level help: one small conceptual cue or one focused question. "
        "Do not perform the algebraic or procedural step for the student. "
        "Leave meaningful work for the student."
    ),
    TutorState.HINT_1: (
        "Give a stronger, more concrete scaffold than first-level help. Identify the relevant "
        "operation, relation, formula, or sub-step, but do not execute it for the student. "
        "Leave meaningful work for the student."
    ),
    TutorState.HINT_2: (
        "Explain exactly one useful intermediate step. Stop after that step and ask the student "
        "to continue. Do not provide a complete worked solution."
    ),
    TutorState.EXPLAIN_STEP: (
        "Focus on the already introduced step: ask the student to apply or justify it. Do not add "
        "further worked steps or provide a complete solution."
    ),
    TutorState.VERIFY: "Ask the student to verify the reasoning or result without introducing a new solution.",
    TutorState.TRANSFER: "Ask the student to apply the learned idea to a closely related case.",
    TutorState.COMPLETE: "Acknowledge completion and invite a brief reflection on the strategy used.",
    TutorState.DIAGNOSE: "Ask one focused question to clarify the student's understanding of the problem.",
}


class TutorAI:
    def __init__(self):
        self.settings = get_settings()
        if not self.settings.openai_api_key:
            self.client = None
            return

        base_url = self.settings.openai_base_url.strip()
        if base_url:
            self.client = OpenAI(
                api_key=self.settings.openai_api_key,
                base_url=base_url,
            )
        else:
            self.client = OpenAI(api_key=self.settings.openai_api_key)

    def analyze_problem(self, problem_text: str, image_data_url: str | None = None) -> ProblemAnalysis:
        if not self.client:
            text = problem_text.strip() or "Bài toán từ ảnh (demo mode: chưa có OPENAI_API_KEY)."
            return ProblemAnalysis(
                normalized_problem=text,
                subject="math",
                grade_band="unknown",
                skills=["general.problem_solving"],
                prerequisites=[],
                expected_answer="",
                verification_notes="Demo mode. Configure OPENAI_API_KEY for image understanding and structured analysis.",
                confidence=0.2,
            )

        content: list[dict] = [{"type": "input_text", "text": problem_text or "Hãy đọc và phân tích bài tập trong ảnh."}]
        if image_data_url:
            content.append({"type": "input_image", "image_url": image_data_url, "detail": "auto"})

        return self._parse_structured(
            ProblemAnalysis,
            responses_input=[
                {"role": "system", "content": ANALYZE_PROMPT},
                {"role": "user", "content": content},
            ],
            chat_messages=[
                {"role": "system", "content": ANALYZE_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": problem_text or "Hãy đọc và phân tích bài tập trong ảnh."},
                        *(
                            [
                                {
                                    "type": "image_url",
                                    "image_url": {"url": image_data_url, "detail": "auto"},
                                }
                            ]
                            if image_data_url
                            else []
                        ),
                    ],
                },
            ],
        )

    def first_turn(self, analysis: ProblemAnalysis, grade: int | None) -> TutorTurn:
        if not self.client:
            turn = TutorTurn(
                message="Em hãy nói cho thầy/cô biết: em đã hiểu đề bài yêu cầu tìm gì chưa? Hãy thử nêu bước đầu tiên em định làm.",
                next_action="ask_student",
                hint_level=0,
                skill_tags=analysis.skills,
            )
            return self._with_first_turn_state(turn)

        context = (
            f"Grade: {grade or 'unknown'}\n"
            f"Problem: {analysis.normalized_problem}\n"
            f"Skills: {', '.join(analysis.skills)}\n"
            f"Prerequisites: {', '.join(analysis.prerequisites)}\n"
            "Begin the tutoring session. Do not reveal the final answer yet."
        )
        turn = self._parse_structured(
            TutorTurn,
            responses_input=[
                {"role": "system", "content": TUTOR_PROMPT},
                {"role": "user", "content": context},
            ],
            chat_messages=[
                {"role": "system", "content": TUTOR_PROMPT},
                {"role": "user", "content": context},
            ],
        )
        return self._with_first_turn_state(turn)

    def continue_turn(
        self,
        problem: str,
        skill: str,
        history: list[tuple[str, str]],
        student_message: str,
        *,
        current_state: TutorState = TutorState.ASK_ATTEMPT,
        intent: TutorReplyIntent = TutorReplyIntent.ATTEMPT,
    ) -> TutorTurn:
        target_state = current_state
        if intent is TutorReplyIntent.HINT_REQUEST:
            target_state = transition_tutor_state(
                TutorTransitionInput(
                    state=current_state,
                    event=TutorTransitionEvent.HINT_REQUESTED,
                )
            )

        if not self.client:
            turn = TutorTurn(
                message="Em thử giải thích vì sao em chọn bước đó. Nếu chưa chắc, hãy viết điều kiện hoặc công thức liên quan trước.",
                next_action="ask_student",
                hint_level=1,
                skill_tags=[skill],
            )
            if intent is TutorReplyIntent.HINT_REQUEST:
                return self._normalize_turn(turn, target_state)
            return self._with_continued_turn_state(turn, current_state)

        transcript = "\n".join(f"{role}: {content}" for role, content in history[-12:])
        generation_policy = self._generation_policy(target_state)
        if intent is TutorReplyIntent.HINT_REQUEST:
            policy_instructions = (
                "The student explicitly requested more help. Generate exactly the assistance "
                f"for target state {target_state.value}: {generation_policy}"
            )
        elif current_state in _ATTEMPT_STATES:
            policy_instructions = (
                f"Attempt response policy: {_ATTEMPT_RESPONSE_POLICY}\n"
                f"Current-state assistance policy (only for a clearly incorrect attempt): "
                f"{generation_policy}"
            )
        else:
            policy_instructions = f"Current-state generation policy: {generation_policy}"
        prompt = (
            f"Problem: {problem}\nPrimary skill: {skill}\n"
            f"Current tutor state: {target_state.value}\n"
            f"{policy_instructions}\n\n"
            f"Recent transcript:\n{transcript}\n\n"
            f"Student's newest message: {student_message}"
        )
        turn = self._parse_structured(
            TutorTurn,
            responses_input=[
                {"role": "system", "content": TUTOR_PROMPT},
                {"role": "user", "content": prompt},
            ],
            chat_messages=[
                {"role": "system", "content": TUTOR_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        if intent is TutorReplyIntent.HINT_REQUEST:
            return self._normalize_turn(turn, target_state)
        return self._with_continued_turn_state(turn, current_state)

    def _parse_structured(
        self,
        expected_model: type[StructuredModel],
        *,
        responses_input: list[dict[str, Any]],
        chat_messages: list[dict[str, Any]],
    ) -> StructuredModel:
        api_mode = getattr(self.settings, "openai_api_mode", "responses")
        if api_mode == "responses":
            response = self.client.responses.parse(
                model=self.settings.openai_model,
                input=responses_input,
                text_format=expected_model,
            )
            return response.output_parsed

        if api_mode == "chat_completions":
            response = self.client.chat.completions.parse(
                model=self.settings.openai_model,
                messages=chat_messages,
                response_format=expected_model,
            )
            parsed = response.choices[0].message.parsed
            if parsed is None:
                raise RuntimeError("Chat Completions response did not include parsed output")
            return parsed

        raise ValueError(f"Unsupported OpenAI API mode: {api_mode}")

    @staticmethod
    def _with_first_turn_state(turn: TutorTurn) -> TutorTurn:
        state = transition_tutor_state(
            TutorTransitionInput(
                state=TutorState.DIAGNOSE,
                event=TutorTransitionEvent.ANALYSIS_READY,
            )
        )
        return TutorAI._normalize_turn(turn, state)

    @staticmethod
    def _with_continued_turn_state(turn: TutorTurn, current_state: TutorState) -> TutorTurn:
        event = None
        if current_state in _ATTEMPT_STATES:
            if turn.likely_correct is True:
                event = TutorTransitionEvent.ATTEMPT_CORRECT
            elif turn.likely_correct is False:
                event = TutorTransitionEvent.ATTEMPT_INCORRECT

        if event is None:
            return TutorAI._normalize_turn(turn, current_state)

        state = transition_tutor_state(TutorTransitionInput(state=current_state, event=event))
        return TutorAI._normalize_turn(turn, state)

    @staticmethod
    def _generation_policy(current_state: TutorState) -> str:
        return _STATE_GENERATION_POLICIES[current_state]

    @staticmethod
    def _normalize_turn(turn: TutorTurn, state: TutorState) -> TutorTurn:
        return turn.model_copy(
            update={
                "state": state,
                "hint_level": _STATE_HINT_LEVELS.get(state, 0),
            }
        )

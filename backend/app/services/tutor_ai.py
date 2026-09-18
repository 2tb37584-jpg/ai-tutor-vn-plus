from __future__ import annotations
from openai import OpenAI
from app.core.config import get_settings
from app.schemas.tutor import ProblemAnalysis, TutorState, TutorTransitionEvent, TutorTransitionInput, TutorTurn
from app.services.tutor_state import transition_tutor_state

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


class TutorAI:
    def __init__(self):
        self.settings = get_settings()
        self.client = OpenAI(api_key=self.settings.openai_api_key) if self.settings.openai_api_key else None

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

        response = self.client.responses.parse(
            model=self.settings.openai_model,
            input=[
                {"role": "system", "content": ANALYZE_PROMPT},
                {"role": "user", "content": content},
            ],
            text_format=ProblemAnalysis,
        )
        return response.output_parsed

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
        response = self.client.responses.parse(
            model=self.settings.openai_model,
            input=[
                {"role": "system", "content": TUTOR_PROMPT},
                {"role": "user", "content": context},
            ],
            text_format=TutorTurn,
        )
        return self._with_first_turn_state(response.output_parsed)

    def continue_turn(
        self,
        problem: str,
        skill: str,
        history: list[tuple[str, str]],
        student_message: str,
        *,
        current_state: TutorState = TutorState.ASK_ATTEMPT,
    ) -> TutorTurn:
        if not self.client:
            turn = TutorTurn(
                message="Em thử giải thích vì sao em chọn bước đó. Nếu chưa chắc, hãy viết điều kiện hoặc công thức liên quan trước.",
                next_action="ask_student",
                hint_level=1,
                skill_tags=[skill],
            )
            return self._with_continued_turn_state(turn, current_state)

        transcript = "\n".join(f"{role}: {content}" for role, content in history[-12:])
        prompt = (
            f"Problem: {problem}\nPrimary skill: {skill}\n\n"
            f"Recent transcript:\n{transcript}\n\n"
            f"Student's newest message: {student_message}"
        )
        response = self.client.responses.parse(
            model=self.settings.openai_model,
            input=[
                {"role": "system", "content": TUTOR_PROMPT},
                {"role": "user", "content": prompt},
            ],
            text_format=TutorTurn,
        )
        return self._with_continued_turn_state(response.output_parsed, current_state)

    @staticmethod
    def _with_first_turn_state(turn: TutorTurn) -> TutorTurn:
        state = transition_tutor_state(
            TutorTransitionInput(
                state=TutorState.DIAGNOSE,
                event=TutorTransitionEvent.ANALYSIS_READY,
            )
        )
        return turn.model_copy(update={"state": state})

    @staticmethod
    def _with_continued_turn_state(turn: TutorTurn, current_state: TutorState) -> TutorTurn:
        event = None
        if current_state in {TutorState.ASK_ATTEMPT, TutorState.HINT_1, TutorState.HINT_2}:
            if turn.likely_correct is True:
                event = TutorTransitionEvent.ATTEMPT_CORRECT
            elif turn.likely_correct is False:
                event = TutorTransitionEvent.ATTEMPT_INCORRECT

        if event is None:
            return turn.model_copy(update={"state": current_state})

        state = transition_tutor_state(TutorTransitionInput(state=current_state, event=event))
        return turn.model_copy(update={"state": state})

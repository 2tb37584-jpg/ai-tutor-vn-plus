from pydantic import BaseModel, Field


class ProblemAnalysis(BaseModel):
    normalized_problem: str
    subject: str = "math"
    grade_band: str = "unknown"
    skills: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    expected_answer: str = ""
    verification_notes: str = ""
    confidence: float = Field(default=0.5, ge=0, le=1)


class TutorTurn(BaseModel):
    message: str
    next_action: str = "ask_student"
    hint_level: int = Field(default=0, ge=0, le=5)
    skill_tags: list[str] = Field(default_factory=list)
    misconception: str | None = None
    likely_correct: bool | None = None
    reveal_final_answer: bool = False


class StartTutorRequest(BaseModel):
    student_id: int
    problem_text: str = ""
    image_data_url: str | None = None


class StartTutorResponse(BaseModel):
    session_id: int
    analysis: ProblemAnalysis
    tutor: TutorTurn


class TutorReplyRequest(BaseModel):
    session_id: int
    student_message: str = Field(min_length=1, max_length=8000)


class TutorReplyResponse(BaseModel):
    tutor: TutorTurn


class AttemptRequest(BaseModel):
    student_id: int
    session_id: int | None = None
    skill_code: str
    correct: bool
    hint_count: int = Field(default=0, ge=0, le=20)
    misconception: str | None = None

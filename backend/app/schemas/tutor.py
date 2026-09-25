from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class TutorState(str, Enum):
    DIAGNOSE = "diagnose"
    ASK_ATTEMPT = "ask_attempt"
    HINT_1 = "hint_1"
    HINT_2 = "hint_2"
    EXPLAIN_STEP = "explain_step"
    VERIFY = "verify"
    TRANSFER = "transfer"
    COMPLETE = "complete"


class TutorTransitionEvent(str, Enum):
    ANALYSIS_READY = "analysis_ready"
    ATTEMPT_CORRECT = "attempt_correct"
    ATTEMPT_INCORRECT = "attempt_incorrect"
    STEP_EXPLAINED = "step_explained"
    VERIFIED = "verified"
    VERIFICATION_FAILED = "verification_failed"
    TRANSFER_COMPLETED = "transfer_completed"
    HINT_REQUESTED = "hint_requested"


class TutorReplyIntent(str, Enum):
    ATTEMPT = "attempt"
    HINT_REQUEST = "hint_request"


class TutorTransitionInput(BaseModel):
    state: TutorState
    event: TutorTransitionEvent


class ProblemAnalysis(BaseModel):
    normalized_problem: str
    subject: str = "math"
    grade_band: str = "unknown"
    skills: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    expected_answer: str = ""
    verification_notes: str = ""
    confidence: float = Field(default=0.5, ge=0, le=1)


class StudentProblemAnalysis(BaseModel):
    normalized_problem: str
    subject: str
    grade_band: str
    skills: list[str]
    prerequisites: list[str]
    confidence: float = Field(ge=0, le=1)


class TutorTurn(BaseModel):
    message: str
    state: TutorState = TutorState.DIAGNOSE
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


class StartAuthoredTutorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: int
    question_id: str = Field(min_length=1, max_length=120)


class StartTutorResponse(BaseModel):
    session_id: int
    analysis: StudentProblemAnalysis
    tutor: TutorTurn


class NextLearningAction(BaseModel):
    question_id: str
    skill_code: str
    problem_text: str
    difficulty: int


class StartAuthoredTutorResponse(BaseModel):
    session_id: int
    question: NextLearningAction
    tutor: TutorTurn


class TutorReplyRequest(BaseModel):
    session_id: int
    student_message: str = Field(min_length=1, max_length=8000)
    intent: TutorReplyIntent = TutorReplyIntent.ATTEMPT


class TutorReplyResponse(BaseModel):
    tutor: TutorTurn
    next_learning_action: NextLearningAction | None = None


class TutorSessionSummaryResponse(BaseModel):
    session_id: int
    primary_skill: str
    current_state: TutorState
    student_reply_count: int
    attempt_reply_count: int
    hint_request_count: int
    unclassified_reply_count: int
    timed_reply_count: int
    average_response_latency_ms: float | None


class AttemptRequest(BaseModel):
    student_id: int
    session_id: int | None = None
    skill_code: str
    correct: bool
    hint_count: int = Field(default=0, ge=0, le=20)
    misconception: str | None = None


class AttemptResponse(BaseModel):
    ok: bool = True
    mastery_updated: bool
    mastery_reason: str
    mastery_before: float | None = None
    mastery_after: float | None = None

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class PilotStatusOut(BaseModel):
    pilot_id: str
    phase: Literal["pre", "intervention", "post", "complete"]
    skills_total: int = Field(ge=0)
    pre_completed_skills: int = Field(ge=0)
    learning_completed_skills: int = Field(ge=0)
    post_completed_skills: int = Field(ge=0)


class PilotAssessmentItemOut(BaseModel):
    phase: Literal["pre", "post"]
    question_id: str = Field(min_length=1, max_length=120)
    skill_code: str = Field(min_length=1, max_length=120)
    problem_text: str = Field(min_length=1)
    difficulty: int = Field(ge=0)


class PilotAssessmentSubmissionIn(BaseModel):
    question_id: str = Field(min_length=1, max_length=120)
    candidate: str = Field(min_length=1, max_length=4000)

    model_config = {"extra": "forbid"}

    @field_validator("question_id", "candidate")
    @classmethod
    def reject_blank_values(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value

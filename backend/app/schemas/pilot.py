from typing import Literal

from pydantic import BaseModel, Field


class PilotStatusOut(BaseModel):
    pilot_id: str
    phase: Literal["pre", "intervention", "post", "complete"]
    skills_total: int = Field(ge=0)
    pre_completed_skills: int = Field(ge=0)
    learning_completed_skills: int = Field(ge=0)
    post_completed_skills: int = Field(ge=0)

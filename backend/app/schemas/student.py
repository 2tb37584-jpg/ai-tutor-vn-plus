from pydantic import BaseModel, Field


class StudentCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    grade: int | None = Field(default=None, ge=1, le=12)
    preferred_language: str = Field(default="vi", max_length=16)


class StudentOut(BaseModel):
    id: int
    display_name: str
    grade: int | None
    preferred_language: str

    model_config = {"from_attributes": True}


class MasteryOut(BaseModel):
    skill_code: str
    probability: float
    exposures: int
    correct_streak: int

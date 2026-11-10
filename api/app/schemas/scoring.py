from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Evidence(BaseModel):
    turn: int = Field(ge=0)  # index of the transcript entry
    quote: str = Field(min_length=2, max_length=300)


class ScorerOutput(BaseModel):
    """What the LLM must return for one criterion."""

    score: int = Field(ge=1, le=5)
    reason: str = Field(min_length=5, max_length=400)
    evidence: list[Evidence] = Field(min_length=1, max_length=4)


class Criterion(BaseModel):
    key: str = Field(min_length=2, max_length=40)
    name: str
    description: str
    levels: dict[int, str]  # 1..5 -> what that score means
    weight: float = Field(default=1.0, gt=0)

    @field_validator("levels")
    @classmethod
    def levels_cover_1_to_5(cls, v: dict[int, str]) -> dict[int, str]:
        if sorted(v) != [1, 2, 3, 4, 5]:
            raise ValueError("levels must define exactly the scores 1 to 5")
        return v


class CriterionResult(BaseModel):
    key: str
    name: str
    weight: float
    status: Literal["ok", "unverified", "failed"]
    score: int | None = None
    reason: str = ""
    evidence: list[Evidence] = []


class Report(BaseModel):
    overall_score: float | None
    recommendation: Literal["hire", "maybe", "no_hire", "insufficient_data"]
    advice_note: str
    coverage: float  # share of rubric weight that was scored and verified
    criteria: list[CriterionResult]
    strengths: list[str]
    concerns: list[str]

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.scoring import Criterion, Report


class CandidateRow(BaseModel):
    application_id: uuid.UUID
    candidate_email: str
    application_status: str
    report_status: str | None  # None = not scored yet
    overall_score: float | None
    recommendation: str | None


class ReportOut(BaseModel):
    application_id: uuid.UUID
    status: str
    error: str | None
    report: Report | None
    updated_at: datetime


class ReplayTurn(BaseModel):
    index: int
    role: str
    text: str
    seqs: list[int]


class ReplayEvidence(BaseModel):
    criterion_key: str
    criterion_name: str
    turn: int
    quote: str


class ReplayOut(BaseModel):
    turns: list[ReplayTurn]
    evidence: list[ReplayEvidence]


class RubricIn(BaseModel):
    criteria: list[Criterion] = Field(min_length=1, max_length=8)

    @field_validator("criteria")
    @classmethod
    def keys_unique(cls, v: list[Criterion]) -> list[Criterion]:
        keys = [c.key for c in v]
        if len(set(keys)) != len(keys):
            raise ValueError("criterion keys must be unique")
        return v


class RubricOut(BaseModel):
    job_id: uuid.UUID
    is_default: bool
    criteria: list[Criterion]


class MatchRow(BaseModel):
    application_id: uuid.UUID
    candidate_email: str
    match_score: float
    interview_component: float
    similarity: float | None
    passed_filters: bool
    reasons: list[str]
    computed_at: datetime


class MustHavesIn(BaseModel):
    must_haves: list[str] = Field(max_length=15)

    @field_validator("must_haves")
    @classmethod
    def clean(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for term in (t.strip() for t in v):
            if term and term.lower() not in {o.lower() for o in out}:
                out.append(term)
        return out


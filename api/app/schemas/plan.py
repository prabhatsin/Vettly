from typing import Literal

from pydantic import BaseModel, Field, model_validator
import uuid

Category = Literal["resume_verification", "technical_depth", "behavioral"]

class PlanQuestion(BaseModel):
    category: Category
    question: str = Field(min_length=10, max_length=400)
    why: str = Field(min_length=5, max_length=300)



class InterviewPlanData(BaseModel):
    questions: list[PlanQuestion] = Field(min_length=8, max_length=10)

    @model_validator(mode="after")
    def has_every_category(self):
        found = {q.category for q in self.questions}
        missing = {"resume_verification", "technical_depth", "behavioral"} - found
        if missing:
            raise ValueError(f"plan is missing categories: {sorted(missing)}")
        return self

class PlanResponse(BaseModel):
    application_id: uuid.UUID
    questions: list[PlanQuestion]    
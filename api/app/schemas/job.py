import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.job import EmploymentType


class JobCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=10, max_length=10000)
    location: str | None = Field(default=None, max_length=200)
    employment_type: EmploymentType


class JobUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, min_length=10, max_length=10000)
    location: str | None = Field(default=None, max_length=200)
    employment_type: EmploymentType | None = None
    is_active: bool | None = None


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employer_id: uuid.UUID
    title: str
    description: str
    location: str | None
    employment_type: EmploymentType
    is_active: bool
    created_at: datetime
    updated_at: datetime
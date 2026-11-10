import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import settings


class OfferIn(BaseModel):
    role_title: str = Field(min_length=2, max_length=200)
    rate_amount: int = Field(gt=0)
    rate_period: Literal["hour", "month", "year"]
    currency: str = Field(default="INR", pattern="^[A-Z]{3}$")
    start_date: date
    expires_in_days: int = Field(default_factory=lambda: settings.offer_expiry_days, ge=1, le=30)

    @field_validator("start_date")
    @classmethod
    def not_in_past(cls, v: date) -> date:
        if v < date.today():
            raise ValueError("start_date can't be in the past")
        return v


class OfferOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID
    role_title: str
    rate_amount: int
    rate_period: str
    currency: str
    start_date: date
    expires_at: datetime
    status: str
    created_at: datetime
    responded_at: datetime | None


class NoteIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)

class CandidateOfferOut(OfferOut):
    job_title: str
    application_status: str
    funded: bool
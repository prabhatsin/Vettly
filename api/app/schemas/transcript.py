from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TranscriptEntryIn(BaseModel):
    role: Literal["candidate", "interviewer"]
    text: str = Field(min_length=1, max_length=5000)


class TranscriptSave(BaseModel):
    entries: list[TranscriptEntryIn] = Field(max_length=1000)


class TranscriptEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int
    role: str
    text: str
    created_at: datetime
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CandidateMatch(Base):
    """One match result per application, recomputed on demand."""

    __tablename__ = "candidate_matches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), unique=True, index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    match_score: Mapped[float] = mapped_column(Float)
    interview_component: Mapped[float] = mapped_column(Float)
    similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    passed_filters: Mapped[bool] = mapped_column(Boolean)
    reasons: Mapped[list] = mapped_column(JSONB)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
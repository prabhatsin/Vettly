import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class InterviewReport(Base):
    """One scoring result per application. status: pending, done or failed."""

    __tablename__ = "interview_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), default="pending")
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    recommendation: Mapped[str | None] = mapped_column(String(30), nullable=True)
    report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    rubric: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # criteria used
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

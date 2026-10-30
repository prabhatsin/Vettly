import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, func,Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ApplicationStatus(str, enum.Enum):
    submitted = "submitted"
    interviewed = "interviewed"
    shortlisted = "shortlisted"
    rejected = "rejected"
    hired = "hired"


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = ( UniqueConstraint("job_id", "candidate_id", name="uq_application_job_candidate"),)

    id: Mapped[uuid.UUID] = mapped_column( UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[uuid.UUID] = mapped_column( UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    resume_path: Mapped[str] = mapped_column(String(500))
    resume_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus, name="application_status"),
        default=ApplicationStatus.submitted,
        server_default="submitted",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column( DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

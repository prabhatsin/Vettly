import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Offer(Base):
    """One offer per application. status: pending, accepted, declined or expired."""

    __tablename__ = "offers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), unique=True, index=True
    )
    role_title: Mapped[str] = mapped_column(String(200))
    rate_amount: Mapped[int] = mapped_column(Integer)  # whole currency units, e.g. 1500
    rate_period: Mapped[str] = mapped_column(String(10))  # hour, month or year
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    start_date: Mapped[date] = mapped_column(Date)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
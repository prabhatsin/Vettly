import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Payment(Base):
    """Test-mode escrow for an offer. status: pending, succeeded, failed, released or refunded."""

    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("offer_id", "kind", name="uq_payment_offer_kind"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    offer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("offers.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20), default="funding")
    amount: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    provider: Mapped[str] = mapped_column(String(20), default="fake")
    provider_intent_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
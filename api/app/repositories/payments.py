import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.payments import Payment


class PaymentRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, payment: Payment) -> Payment:
        self.db.add(payment)
        return payment

    def get_by_key(self, key: str) -> Payment | None:
        return self.db.scalar(select(Payment).where(Payment.idempotency_key == key))

    def get_for_offer(self, offer_id: uuid.UUID, kind: str = "funding") -> Payment | None:
        return self.db.scalar(select(Payment).where(Payment.offer_id == offer_id, Payment.kind == kind))

    def get_by_intent(self, intent_id: str) -> Payment | None:
        """Locked, so two deliveries of the same webhook can't both apply."""
        return self.db.scalar(
            select(Payment).where(Payment.provider_intent_id == intent_id).with_for_update()
        )
import logging
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import fake_payments
from app.models.offer import Offer
from app.models.payments import Payment
from app.models.user import User
from app.repositories.application import ApplicationRepository
from app.repositories.offer import OfferRepository
from app.repositories.payments import PaymentRepository
from app.services.employer import EmployerService, NotFound
from app.services.hiring import HiringService
from app.services.notifications import NotificationService

logger = logging.getLogger("uvicorn.error")


class PaymentConflict(Exception):
    pass


class PaymentService:
    def __init__(self, db: Session, create_intent=None):
        self.db = db
        self.create_intent = create_intent or fake_payments.create_intent
        self.employer = EmployerService(db)
        self.hiring = HiringService(db)
        self.offers = OfferRepository(db)
        self.payments = PaymentRepository(db)
        self.applications = ApplicationRepository(db)
        self.notes = NotificationService(db)

    def _own_offer(self, application_id: uuid.UUID, employer: User) -> Offer:
        self.employer.own_application(application_id, employer)
        offer = self.offers.get_by_application(application_id)
        if offer is None:
            raise NotFound()
        return self.hiring.expire_if_due(offer)

    def fund(self, application_id: uuid.UUID, employer: User, idempotency_key: str) -> Payment:
        offer = self._own_offer(application_id, employer)

        same_key = self.payments.get_by_key(idempotency_key)
        if same_key:  # a retry of the same request
            if same_key.offer_id != offer.id:
                raise PaymentConflict("Idempotency-Key was already used for another payment")
            return same_key

        existing = self.payments.get_for_offer(offer.id)
        if existing and existing.status != "failed":  # funding already started: never charge twice
            return existing
        if offer.status != "pending":
            raise PaymentConflict(f"Offer is {offer.status}")

        if existing:  # last attempt failed: retry on the same row with the new key
            payment = existing
            payment.idempotency_key = idempotency_key
            payment.status = "pending"
        else:
            payment = self.payments.add(Payment(
                offer_id=offer.id, amount=offer.rate_amount, currency=offer.currency,
                idempotency_key=idempotency_key,
            ))
        try:
            self.db.commit()  # the row exists before the provider is called
        except IntegrityError:  # a parallel request got there first
            self.db.rollback()
            return self.payments.get_by_key(idempotency_key) or self.payments.get_for_offer(offer.id)

        payment.provider_intent_id = self.create_intent(
            payment.amount, payment.currency, idempotency_key, {"payment_id": str(payment.id)}
        )
        self.db.commit()
        return payment

    def get(self, application_id: uuid.UUID, employer: User) -> Payment:
        offer = self._own_offer(application_id, employer)
        payment = self.payments.get_for_offer(offer.id)
        if payment is None:
            raise NotFound()
        return payment

    def handle_event(self, event: dict) -> None:
        """Webhook from the provider: the only thing that marks a payment paid."""
        intent_id = (event.get("data") or {}).get("intent_id")
        payment = self.payments.get_by_intent(intent_id) if intent_id else None
        if payment is None:
            logger.warning("webhook for unknown intent %s", intent_id)
            return
        if payment.status != "pending":  # duplicate or late delivery
            return
        if event.get("type") == "payment_intent.succeeded":
            payment.status = "succeeded"
        elif event.get("type") == "payment_intent.payment_failed":
            payment.status = "failed"
        else:
            return

        offer = self.offers.get_by_id(payment.offer_id)
        if payment.status == "succeeded" and offer.status != "pending":
            payment.status = "refunded"  # paid after the offer closed
        self.db.commit()

        app = self.applications.get_by_id(offer.application_id)
        if payment.status == "succeeded":
            self.notes.notify(app.candidate_id, "offer_funded",
                              f"Your offer for {offer.role_title} is funded. You can accept it now.",
                              {"offer_id": offer.id})
            if offer.created_by:
                self.notes.notify(offer.created_by, "payment_succeeded",
                                  f"Payment of {payment.amount} {payment.currency} confirmed.",
                                  {"offer_id": offer.id, "payment_id": payment.id})
        elif payment.status == "failed" and offer.created_by:
            self.notes.notify(offer.created_by, "payment_failed",
                              "Payment failed. You can try funding again.",
                              {"offer_id": offer.id, "payment_id": payment.id})
import uuid

from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.application import ApplicationStatus as S
from app.models.offer import Offer
from app.models.user import User
from app.repositories.application import ApplicationRepository
from app.repositories.offer import OfferRepository
from app.repositories.payments import PaymentRepository
from app.schemas.offer import CandidateOfferOut, OfferOut
from app.services.hiring import HiringService, utcnow
from app.services.notifications import NotificationService
from app.services.status_machine import ApplicationStatusService, InvalidTransition


class OfferNotFound(Exception):
    pass


class OfferConflict(Exception):
    pass


class CandidateOfferService:
    def __init__(self, db: Session):
        self.db = db
        self.offers = OfferRepository(db)
        self.payments = PaymentRepository(db)
        self.applications = ApplicationRepository(db)
        self.status = ApplicationStatusService(db)
        self.hiring = HiringService(db)
        self.notes = NotificationService(db)

    def list_mine(self, candidate: User) -> list[CandidateOfferOut]:
        out = []
        for offer, job_title, app in self.offers.list_for_candidate(candidate.id):
            self.hiring.expire_if_due(offer)
            payment = self.payments.get_for_offer(offer.id)
            out.append(CandidateOfferOut(
                **OfferOut.model_validate(offer).model_dump(),
                job_title=job_title,
                application_status=app.status.value,
                funded=payment is not None and payment.status in ("succeeded", "released"),
            ))
        return out

    def _own(self, offer_id: uuid.UUID, candidate: User) -> tuple[Offer, Application]:
        offer = self.offers.get_by_id(offer_id)
        app = self.applications.get_by_id(offer.application_id) if offer else None
        if app is None or app.candidate_id != candidate.id:
            raise OfferNotFound()
        return self.hiring.expire_if_due(offer), app

    def _move(self, app: Application, target: S, candidate: User, note: str) -> None:
        try:
            self.status.move(app, target, candidate, note)  # commits offer + payment changes too
        except InvalidTransition:
            self.db.rollback()
            raise

    def accept(self, offer_id: uuid.UUID, candidate: User) -> Offer:
        offer, app = self._own(offer_id, candidate)
        if offer.status != "pending":
            raise OfferConflict(f"Offer is {offer.status}")
        payment = self.payments.get_for_offer(offer.id)
        if payment is None or payment.status != "succeeded":
            raise OfferConflict("Offer isn't funded yet")
        offer.status = "accepted"
        offer.responded_at = utcnow()
        payment.status = "released"
        self._move(app, S.accepted, candidate, "offer accepted")
        if offer.created_by:
            self.notes.notify(offer.created_by, "offer_accepted",
                              f"{candidate.email} accepted the offer for {offer.role_title}.",
                              {"offer_id": offer.id, "application_id": app.id})
        return offer

    def decline(self, offer_id: uuid.UUID, candidate: User) -> Offer:
        offer, app = self._own(offer_id, candidate)
        if offer.status != "pending":
            raise OfferConflict(f"Offer is {offer.status}")
        offer.status = "declined"
        offer.responded_at = utcnow()
        payment = self.payments.get_for_offer(offer.id)
        if payment and payment.status == "succeeded":
            payment.status = "refunded"
        self._move(app, S.declined, candidate, "offer declined")
        if offer.created_by:
            self.notes.notify(offer.created_by, "offer_declined",
                              f"{candidate.email} declined the offer for {offer.role_title}.",
                              {"offer_id": offer.id, "application_id": app.id})
        return offer
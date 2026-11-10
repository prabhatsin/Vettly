import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.application import ApplicationStatus as S
from app.models.offer import Offer
from app.models.user import User
from app.repositories.offer import OfferRepository
from app.repositories.payments import PaymentRepository
from app.schemas.offer import OfferIn
from app.services.employer import EmployerService, NotFound
from app.services.notifications import NotificationService
from app.services.status_machine import ApplicationStatusService, InvalidTransition


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HiringService:
    def __init__(self, db: Session):
        self.db = db
        self.employer = EmployerService(db)
        self.status = ApplicationStatusService(db)
        self.offers = OfferRepository(db)
        self.payments = PaymentRepository(db)
        self.notes = NotificationService(db)

    def _job_title(self, app: Application) -> str:
        job = self.employer.jobs.get_by_id(app.job_id)
        return job.title if job else "a job"

    def shortlist(self, application_id: uuid.UUID, employer: User, note: str | None = None) -> Application:
        app = self.employer.own_application(application_id, employer)
        self.status.move(app, S.shortlisted, employer, note)
        self.notes.notify(app.candidate_id, "shortlisted",
                          f"You've been shortlisted for {self._job_title(app)}.",
                          {"application_id": app.id})
        return app

    def reject(self, application_id: uuid.UUID, employer: User, note: str | None = None) -> Application:
        app = self.employer.own_application(application_id, employer)
        self.status.move(app, S.rejected, employer, note)
        self.notes.notify(app.candidate_id, "rejected",
                          f"Your application for {self._job_title(app)} was not taken forward.",
                          {"application_id": app.id})
        return app

    def make_offer(self, application_id: uuid.UUID, employer: User, data: OfferIn) -> Offer:
        app = self.employer.own_application(application_id, employer)
        if not self.status.allowed(app.status, S.offered, employer.role.value):
            raise InvalidTransition(app.status, S.offered)
        offer = self.offers.add(Offer(
            application_id=app.id, role_title=data.role_title, rate_amount=data.rate_amount,
            rate_period=data.rate_period, currency=data.currency, start_date=data.start_date,
            expires_at=utcnow() + timedelta(days=data.expires_in_days), created_by=employer.id,
        ))
        try:
            self.status.move(app, S.offered, employer, note=f"Offer: {data.role_title}")
        except (InvalidTransition, IntegrityError):  # lost a race with another request
            self.db.rollback()
            raise InvalidTransition(app.status, S.offered)
        self.notes.notify(app.candidate_id, "offer",
                          f"New offer for {data.role_title}: {data.rate_amount} {data.currency}/{data.rate_period}.",
                          {"application_id": app.id, "offer_id": offer.id})
        return offer

    def get_offer(self, application_id: uuid.UUID, employer: User) -> Offer:
        self.employer.own_application(application_id, employer)
        offer = self.offers.get_by_application(application_id)
        if offer is None:
            raise NotFound()
        return self.expire_if_due(offer)

    def expire_if_due(self, offer: Offer) -> Offer:
        """Lazy expiry: checked whenever an offer is read or acted on."""
        if offer.status == "pending" and offer.expires_at <= utcnow():
            offer.status = "expired"
            offer.responded_at = utcnow()
            payment = self.payments.get_for_offer(offer.id)
            if payment and payment.status == "succeeded":
                payment.status = "refunded"
            self.status.system_advance(offer.application_id, S.declined, note="offer expired")
            self.db.commit()
            app = self.employer.applications.get_by_id(offer.application_id)
            self.notes.notify(app.candidate_id, "offer_expired",
                              f"Your offer for {offer.role_title} expired.", {"offer_id": offer.id})
            if offer.created_by:
                self.notes.notify(offer.created_by, "offer_expired",
                                  f"Your offer for {offer.role_title} expired without a reply.",
                                  {"offer_id": offer.id})
        return offer


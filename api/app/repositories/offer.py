import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.job import Job
from app.models.offer import Offer


class OfferRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, offer: Offer) -> Offer:
        """Adds without committing; the status move commits it together with the status change."""
        self.db.add(offer)
        return offer

    def get_by_id(self, offer_id: uuid.UUID) -> Offer | None:
        return self.db.get(Offer, offer_id)

    def get_by_application(self, application_id: uuid.UUID) -> Offer | None:
        return self.db.scalar(select(Offer).where(Offer.application_id == application_id))

    def list_for_candidate(self, candidate_id: uuid.UUID) -> list[tuple[Offer, str, Application]]:
        stmt = (
            select(Offer, Job.title, Application)
            .join(Application, Application.id == Offer.application_id)
            .join(Job, Job.id == Application.job_id)
            .where(Application.candidate_id == candidate_id)
            .order_by(Offer.created_at.desc())
        )
        return [tuple(r) for r in self.db.execute(stmt).all()]
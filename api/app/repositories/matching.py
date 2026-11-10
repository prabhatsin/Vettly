import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.match import CandidateMatch
from app.models.user import User


class MatchRepository:
    def __init__(self, db: Session):
        self.db = db

    def save(self, application_id: uuid.UUID, job_id: uuid.UUID, **fields) -> CandidateMatch:
        row = self.db.scalar(
            select(CandidateMatch).where(CandidateMatch.application_id == application_id)
        )
        if row is None:
            row = CandidateMatch(application_id=application_id, job_id=job_id)
            self.db.add(row)
        for key, value in fields.items():
            setattr(row, key, value)
        self.db.commit()
        return row

    def list_for_job(self, job_id: uuid.UUID) -> list[tuple[CandidateMatch, str]]:
        """Candidates who pass the must-haves first, then best match score."""
        stmt = (
            select(CandidateMatch, User.email)
            .join(Application, Application.id == CandidateMatch.application_id)
            .join(User, User.id == Application.candidate_id)
            .where(CandidateMatch.job_id == job_id)
            .order_by(CandidateMatch.passed_filters.desc(), CandidateMatch.match_score.desc())
        )
        return [(m, email) for m, email in self.db.execute(stmt).all()]
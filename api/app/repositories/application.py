import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.application import Application, ApplicationStatus


class ApplicationRepository:
    """All database access for applications: create, get, list by candidate or job."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, job_id: uuid.UUID, candidate_id: uuid.UUID, resume_path: str) -> Application:
        application = Application(
            job_id=job_id, candidate_id=candidate_id, resume_path=resume_path
        )
        self.db.add(application)
        self.db.commit()
        self.db.refresh(application)
        return application

    def get_by_id(self, application_id: uuid.UUID) -> Application | None:
        return self.db.get(Application, application_id)

    def get_by_job_and_candidate(
        self, job_id: uuid.UUID, candidate_id: uuid.UUID
    ) -> Application | None:
        stmt = select(Application).where(
            Application.job_id == job_id, Application.candidate_id == candidate_id
        )
        return self.db.scalar(stmt)

    def list_by_candidate(self, candidate_id: uuid.UUID) -> list[Application]:
        stmt = (
            select(Application)
            .where(Application.candidate_id == candidate_id)
            .order_by(Application.created_at.desc())
        )
        return list(self.db.scalars(stmt))

    def list_by_job(self, job_id: uuid.UUID) -> list[Application]:
        stmt = (
            select(Application)
            .where(Application.job_id == job_id)
            .order_by(Application.created_at.desc())
        )
        return list(self.db.scalars(stmt))

    def update_status(self, application: Application, status: ApplicationStatus) -> Application:
        application.status = status
        self.db.commit()
        self.db.refresh(application)
        return application
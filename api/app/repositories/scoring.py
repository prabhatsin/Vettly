import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.report import InterviewReport
from app.models.rubric import Rubric
from app.models.user import User


class RubricRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_job(self, job_id: uuid.UUID) -> Rubric | None:
        return self.db.scalar(select(Rubric).where(Rubric.job_id == job_id))

    def upsert(self, job_id: uuid.UUID, criteria: list[dict]) -> Rubric:
        row = self.get_by_job(job_id)
        if row is None:
            row = Rubric(job_id=job_id, criteria=criteria)
            self.db.add(row)
        else:
            row.criteria = criteria
        self.db.commit()
        return row


class ReportRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_application(self, application_id: uuid.UUID) -> InterviewReport | None:
        return self.db.scalar(
            select(InterviewReport).where(InterviewReport.application_id == application_id)
        )

    def save(
        self,
        application_id: uuid.UUID,
        *,
        status: str,
        overall_score: float | None = None,
        recommendation: str | None = None,
        report: dict | None = None,
        rubric: list | None = None,
        error: str | None = None,
    ) -> InterviewReport:
        """Create or replace the single report row for this application."""
        row = self.get_by_application(application_id)
        if row is None:
            row = InterviewReport(application_id=application_id)
            self.db.add(row)
        row.status = status
        row.overall_score = overall_score
        row.recommendation = recommendation
        row.report = report
        row.rubric = rubric
        row.error = error
        self.db.commit()
        return row

    def list_for_job(
        self, job_id: uuid.UUID
    ) -> list[tuple[Application, User, InterviewReport | None]]:
        """Every application for a job with its candidate and report, best score first."""
        stmt = (
            select(Application, User, InterviewReport)
            .join(User, User.id == Application.candidate_id)
            .outerjoin(InterviewReport, InterviewReport.application_id == Application.id)
            .where(Application.job_id == job_id)
            .order_by(InterviewReport.overall_score.desc().nulls_last(), Application.created_at)
        )
        return [tuple(row) for row in self.db.execute(stmt).all()]

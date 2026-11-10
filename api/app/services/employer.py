import uuid

from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.job import Job
from app.models.report import InterviewReport
from app.models.user import User
from app.repositories.application import ApplicationRepository
from app.repositories.jobs import JobRepository
from app.repositories.scoring import ReportRepository, RubricRepository
from app.repositories.transcript import TranscriptRepository
from app.schemas.employer import (
    CandidateRow,
    ReplayEvidence,
    ReplayOut,
    ReplayTurn,
    RubricOut,
)
from app.schemas.scoring import Criterion, Report
from app.services.scoring import DEFAULT_RUBRIC, merge_turns


class NotFound(Exception):
    """Missing, or not owned by this employer. Both look the same from outside."""


class EmployerService:
    def __init__(self, db: Session):
        self.applications = ApplicationRepository(db)
        self.jobs = JobRepository(db)
        self.transcripts = TranscriptRepository(db)
        self.reports = ReportRepository(db)
        self.rubrics = RubricRepository(db)

    def _own_job(self, job_id: uuid.UUID, employer: User) -> Job:
        job = self.jobs.get_by_id(job_id)
        if job is None or job.employer_id != employer.id:
            raise NotFound()
        return job

    def own_application(self, application_id: uuid.UUID, employer: User) -> Application:
        application = self.applications.get_by_id(application_id)
        if application is None:
            raise NotFound()
        self._own_job(application.job_id, employer)
        return application

    def candidates(self, job_id: uuid.UUID, employer: User) -> list[CandidateRow]:
        self._own_job(job_id, employer)
        return [
            CandidateRow(
                application_id=app.id,
                candidate_email=user.email,
                application_status=app.status.value,
                report_status=report.status if report else None,
                overall_score=report.overall_score if report else None,
                recommendation=report.recommendation if report else None,
            )
            for app, user, report in self.reports.list_for_job(job_id)
        ]

    def report(self, application_id: uuid.UUID, employer: User) -> InterviewReport:
        self.own_application(application_id, employer)
        row = self.reports.get_by_application(application_id)
        if row is None:
            raise NotFound()
        return row

    def replay(self, application_id: uuid.UUID, employer: User) -> ReplayOut:
        self.own_application(application_id, employer)
        entries = self.transcripts.list_by_application(application_id)
        turns = merge_turns([{"seq": e.seq, "role": e.role, "text": e.text} for e in entries])
        evidence: list[ReplayEvidence] = []
        row = self.reports.get_by_application(application_id)
        if row is not None and row.report:
            for c in Report.model_validate(row.report).criteria:
                evidence += [
                    ReplayEvidence(
                        criterion_key=c.key, criterion_name=c.name, turn=ev.turn, quote=ev.quote
                    )
                    for ev in c.evidence
                ]
        return ReplayOut(
            turns=[ReplayTurn(index=i, **t) for i, t in enumerate(turns)],
            evidence=evidence,
        )

    def get_rubric(self, job_id: uuid.UUID, employer: User) -> RubricOut:
        self._own_job(job_id, employer)
        row = self.rubrics.get_by_job(job_id)
        if row is None:
            return RubricOut(job_id=job_id, is_default=True, criteria=DEFAULT_RUBRIC)
        return RubricOut(
            job_id=job_id,
            is_default=False,
            criteria=[Criterion.model_validate(c) for c in row.criteria],
        )

    def set_rubric(
        self, job_id: uuid.UUID, employer: User, criteria: list[Criterion]
    ) -> RubricOut:
        self._own_job(job_id, employer)
        self.rubrics.upsert(job_id, [c.model_dump(mode="json") for c in criteria])
        return RubricOut(job_id=job_id, is_default=False, criteria=criteria)

import re
import uuid
from typing import Callable

from sqlalchemy.orm import Session

from app.config import settings
from app.models.application import Application
from app.models.job import Job
from app.models.user import User
from app.repositories.application import ApplicationRepository
from app.repositories.jobs import JobRepository
from app.repositories.matching import MatchRepository
from app.repositories.scoring import ReportRepository
from app.schemas.employer import MatchRow
from app.services.embedding import cosine
from app.services.employer import NotFound

Embed = Callable[[str], list[float]]


def has_term(text: str, term: str) -> bool:
    """Whole-word, case-insensitive match, so 'Go' doesn't match 'good'."""
    pattern = r"(?<![A-Za-z0-9])" + re.escape(term.strip()) + r"(?![A-Za-z0-9])"
    return re.search(pattern, text, re.IGNORECASE) is not None


class MatchingService:
    def __init__(self, db: Session, embed: Embed | None = None):
        self.embed = embed
        self.jobs = JobRepository(db)
        self.applications = ApplicationRepository(db)
        self.reports = ReportRepository(db)
        self.matches = MatchRepository(db)

    def _own_job(self, job_id: uuid.UUID, employer: User) -> Job:
        job = self.jobs.get_by_id(job_id)
        if job is None or job.employer_id != employer.id:
            raise NotFound()
        return job

    def ranked(self, job_id: uuid.UUID, employer: User) -> list[MatchRow]:
        self._own_job(job_id, employer)
        return [
            MatchRow(
                application_id=m.application_id, candidate_email=email,
                match_score=m.match_score, interview_component=m.interview_component,
                similarity=m.similarity, passed_filters=m.passed_filters,
                reasons=m.reasons, computed_at=m.computed_at,
            )
            for m, email in self.matches.list_for_job(job_id)
        ]

    def recompute(self, job_id: uuid.UUID, employer: User) -> list[MatchRow]:
        job = self._own_job(job_id, employer)
        rows = self.applications.list_by_job(job_id)
        if rows:
            job_vec = self.embed(f"{job.title}\n{job.description}")
            for application, _email in rows:
                self._score_one(job, job_vec, application)
        return self.ranked(job_id, employer)

    def set_must_haves(self, job_id: uuid.UUID, employer: User, terms: list[str]) -> list[str]:
        job = self._own_job(job_id, employer)
        return self.jobs.set_must_haves(job, terms).must_haves

    def _score_one(self, job: Job, job_vec: list[float], application: Application) -> None:
        reasons: list[str] = []
        text = application.resume_text or ""

        report = self.reports.get_by_application(application.id)
        interview = 0.0
        if report and report.status == "done" and report.overall_score is not None:
            interview = report.overall_score / 5
            reasons.append(f"Interview {report.overall_score:.1f}/5 ({report.recommendation})")
        elif report and report.status == "done":
            reasons.append(f"Interview gave no score ({report.recommendation})")
        else:
            reasons.append("Interview not scored yet")

        similarity = None
        if text.strip():
            if application.resume_embedding is None:
                self.applications.set_resume_embedding(application, self.embed(text))
            similarity = round(cosine(job_vec, application.resume_embedding), 3)
            reasons.append(f"Résumé–job similarity {similarity:.2f}")
        else:
            reasons.append("No résumé text to compare")

        must = job.must_haves or []
        have = [t for t in must if has_term(text, t)]
        missing = [t for t in must if t not in have]
        if have:
            reasons.append("Has: " + ", ".join(have))
        if missing:
            reasons.append("Missing must-have: " + ", ".join(missing))

        score = (settings.match_interview_weight * interview
                 + settings.match_similarity_weight * (similarity or 0.0))
        self.matches.save(
            application.id, job.id,
            match_score=round(score, 3), interview_component=round(interview, 3),
            similarity=similarity, passed_filters=not missing, reasons=reasons,
        )
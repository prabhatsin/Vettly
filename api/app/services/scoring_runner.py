import asyncio
import logging
import uuid

from google import genai
from google.genai import types
from sqlalchemy.orm import Session

from app.config import settings
from app.repositories.application import ApplicationRepository
from app.repositories.jobs import JobRepository
from app.repositories.scoring import ReportRepository, RubricRepository
from app.repositories.transcript import TranscriptRepository
from app.schemas.scoring import Criterion, ScorerOutput
from app.services.scoring import DEFAULT_RUBRIC, Generate, merge_turns, score_interview

from app.models.application import ApplicationStatus
from app.services.status_machine import ApplicationStatusService

logger = logging.getLogger("scoring_runner")

MAX_RESUME_CHARS = 4500


class GeminiScorerClient:
    """Adapts the sync Gemini client to the `generate(prompt) -> ScorerOutput` shape."""

    def __init__(self, client=None, model: str | None = None):
        self.client = client or genai.Client(api_key=settings.google_api_key)
        self.model = model or settings.scoring_model or settings.plan_model

    async def __call__(self, prompt: str) -> ScorerOutput:
        return await asyncio.to_thread(self._call, prompt)

    def _call(self, prompt: str) -> ScorerOutput:
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ScorerOutput,
                temperature=0.0,  # same transcript, similar scores on a re-run
            ),
        )
        return ScorerOutput.model_validate_json(response.text)


def rubric_for_job(db: Session, job_id: uuid.UUID) -> list[Criterion]:
    row = RubricRepository(db).get_by_job(job_id)
    if row is None:
        return DEFAULT_RUBRIC
    return [Criterion.model_validate(c) for c in row.criteria]


class ScoringJob:
    def __init__(self, db: Session, generate: Generate | None = None):
        self.generate = generate or GeminiScorerClient()
        self.applications = ApplicationRepository(db)
        self.jobs = JobRepository(db)
        self.transcripts = TranscriptRepository(db)
        self.reports = ReportRepository(db)
        self.db = db

    async def run(self, application_id: uuid.UUID) -> None:
        application = self.applications.get_by_id(application_id)
        if application is None:
            logger.warning("scoring: application %s not found", application_id)
            return
        job = self.jobs.get_by_id(application.job_id)
        rubric = rubric_for_job(self.db, application.job_id)
        entries = self.transcripts.list_by_application(application_id)
        turns = merge_turns(
            [{"seq": e.seq, "role": e.role, "text": e.text} for e in entries]
        )

        self.reports.save(application_id, status="pending")
        ApplicationStatusService(self.db).system_advance(application_id, ApplicationStatus.scored)
        context = {
            "job_title": job.title if job else "",
            "resume_excerpt": (application.resume_text or "")[:MAX_RESUME_CHARS],
        }
        report = await score_interview(turns, self.generate, rubric, context)
        self.reports.save(
            application_id,
            status="done",
            overall_score=report.overall_score,
            recommendation=report.recommendation,
            report=report.model_dump(mode="json"),
            rubric=[c.model_dump(mode="json") for c in rubric],
        )
        logger.info(
            "scoring: %s done, overall %s, %s",
            application_id, report.overall_score, report.recommendation,
        )

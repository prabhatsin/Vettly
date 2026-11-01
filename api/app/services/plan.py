import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.interview_plan import InterviewPlan
from app.repositories.application import ApplicationRepository
from app.repositories.jobs import JobRepository
from app.repositories.plan import PlanRepository
from app.services.application import ApplicationNotFound
from app.services.plan_generator import PlanGenerator

MAX_EXCERPT_CHARS = 4500


@dataclass
class PlanContext:
    plan: InterviewPlan
    job_title: str
    job_description: str
    resume_excerpt: str


class PlanService:
    def __init__(self, db: Session, generator: PlanGenerator):
        self.applications = ApplicationRepository(db)
        self.jobs = JobRepository(db)
        self.plans = PlanRepository(db)
        self.generator = generator

    def get_or_create(self, application_id: uuid.UUID) -> PlanContext:
        application = self.applications.get_by_id(application_id)
        if application is None:
            raise ApplicationNotFound()

        job = self.jobs.get_by_id(application.job_id)
        if job is None:
            raise ApplicationNotFound()

        plan = self.plans.get_by_application(application_id)
        if plan is None:
            data = self.generator.generate(application.resume_text, job.title, job.description)
            plan = self.plans.create(application_id, data.model_dump())

        text = " ".join((application.resume_text or "").split())
        excerpt = text[:MAX_EXCERPT_CHARS]
        # excerpt = (application.resume_text or "").strip()[:MAX_EXCERPT_CHARS]
        return PlanContext(plan, job.title, job.description, excerpt)
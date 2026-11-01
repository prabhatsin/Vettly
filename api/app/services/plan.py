import uuid

from sqlalchemy.orm import Session
from app.models.interview_plan import InterviewPlan
from app.repositories.application import ApplicationRepository
from app.repositories.jobs import JobRepository
from app.repositories.plan import PlanRepository
from app.services.application import ApplicationNotFound
from app.services.plan_generator import PlanGenerator


class PlanService:
    def __init__(self, db: Session, generator: PlanGenerator):
        self.applications = ApplicationRepository(db)
        self.jobs = JobRepository(db)
        self.plans = PlanRepository(db)
        self.generator = generator

    def get_or_create(self, application_id: uuid.UUID) -> InterviewPlan:
        application = self.applications.get_by_id(application_id)
        if application is None:
            raise ApplicationNotFound()

        existing = self.plans.get_by_application(application_id)
        if existing:
            return existing

        job = self.jobs.get_by_id(application.job_id)
        if job is None:
            raise ApplicationNotFound()

        data = self.generator.generate(application.resume_text, job.title, job.description)
        return self.plans.create(application_id, data.model_dump())


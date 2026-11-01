import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.interview_plan import InterviewPlan


class PlanRepository:
    """All database access for interview plans: get by application, create once."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_application(self, application_id: uuid.UUID) -> InterviewPlan | None:
        """ returns the application’s plan, or None if none exists yet. """
        stmt = select(InterviewPlan).where(InterviewPlan.application_id == application_id)
        return self.db.scalar(stmt)


    def create(self, application_id: uuid.UUID, plan: dict) -> InterviewPlan:
        """stores a plan, but if one already exists (the unique constraint fires, for example when 
        two requests race), it returns the existing plan instead of failing."""

        row = InterviewPlan(application_id=application_id, plan=plan)
        self.db.add(row)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            return self.get_by_application(application_id)
        self.db.refresh(row)
        return row
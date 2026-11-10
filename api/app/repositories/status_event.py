import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.status_event import ApplicationStatusEvent


class StatusEventRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, application_id: uuid.UUID, from_status: str, to_status: str,
            actor_id: uuid.UUID | None, actor_role: str, note: str | None) -> ApplicationStatusEvent:
        """Adds without committing; the status service commits the change and the log together."""
        row = ApplicationStatusEvent(
            application_id=application_id, from_status=from_status, to_status=to_status,
            actor_id=actor_id, actor_role=actor_role, note=note,
        )
        self.db.add(row)
        return row

    def list_for_application(self, application_id: uuid.UUID) -> list[ApplicationStatusEvent]:
        stmt = (
            select(ApplicationStatusEvent)
            .where(ApplicationStatusEvent.application_id == application_id)
            .order_by(ApplicationStatusEvent.created_at)
        )
        return list(self.db.scalars(stmt))
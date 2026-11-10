import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.notification import Notification


class NotificationRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, user_id: uuid.UUID, kind: str, message: str, data: dict) -> Notification:
        row = Notification(user_id=user_id, kind=kind, message=message, data=data)
        self.db.add(row)
        self.db.commit()
        return row

    def list_for_user(self, user_id: uuid.UUID, limit: int = 50) -> list[Notification]:
        stmt = (select(Notification).where(Notification.user_id == user_id)
                .order_by(Notification.created_at.desc()).limit(limit))
        return list(self.db.scalars(stmt))

    def get_by_id(self, notification_id: uuid.UUID) -> Notification | None:
        return self.db.get(Notification, notification_id)

    def mark_read(self, row: Notification) -> Notification:
        if row.read_at is None:
            row.read_at = datetime.now(timezone.utc)
            self.db.commit()
        return row
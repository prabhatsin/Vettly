import logging
import uuid

from sqlalchemy.orm import Session

from app.core import events
from app.models.notification import Notification
from app.models.user import User
from app.repositories.notification import NotificationRepository

logger = logging.getLogger("uvicorn.error")  # uvicorn prints this logger at INFO


class NotificationNotFound(Exception):
    pass


class NotificationService:
    def __init__(self, db: Session):
        self.repo = NotificationRepository(db)

    def notify(self, user_id: uuid.UUID, kind: str, message: str, data: dict | None = None) -> Notification:
        """Saves an in-app notification, pushes it live, and logs a dev 'email'."""
        data = {k: str(v) for k, v in (data or {}).items()}
        row = self.repo.create(user_id, kind, message, data)
        events.publish(user_id, {"type": "notification", "id": str(row.id),
                                 "kind": kind, "message": message, "data": data})
        logger.info("EMAIL (dev) to user %s: %s", user_id, message)
        return row

    def list_mine(self, user: User) -> list[Notification]:
        return self.repo.list_for_user(user.id)

    def mark_read(self, notification_id: uuid.UUID, user: User) -> Notification:
        row = self.repo.get_by_id(notification_id)
        if row is None or row.user_id != user.id:
            raise NotificationNotFound()
        return self.repo.mark_read(row)
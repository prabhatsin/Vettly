import uuid

from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.application import ApplicationStatus as S
from app.models.user import User
from app.repositories.application import ApplicationRepository
from app.repositories.status_event import StatusEventRepository

SYSTEM = "system"

# from-status -> {to-status: roles allowed to make that move}. Anything not listed is refused.
TRANSITIONS: dict[S, dict[S, set[str]]] = {
    S.applied: {S.interviewed: {SYSTEM}, S.rejected: {"employer"}},
    S.interviewed: {S.scored: {SYSTEM}, S.rejected: {"employer"}},
    S.scored: {S.shortlisted: {"employer"}, S.rejected: {"employer"}},
    S.shortlisted: {S.offered: {"employer"}, S.rejected: {"employer"}},
    S.offered: {S.accepted: {"candidate"}, S.declined: {"candidate", SYSTEM}},  # system = offer expired
}


class InvalidTransition(Exception):
    def __init__(self, current: S, target: S):
        super().__init__(f"Cannot move from {current.value} to {target.value}")


class ApplicationStatusService:
    """The only place an application's status may change."""

    def __init__(self, db: Session):
        self.db = db
        self.applications = ApplicationRepository(db)
        self.events = StatusEventRepository(db)

    @staticmethod
    def allowed(current: S, target: S, role: str) -> bool:
        return role in TRANSITIONS.get(current, {}).get(target, set())

    def move(self, application: Application, target: S,
             actor: User | None = None, note: str | None = None) -> Application:
        role = actor.role.value if actor else SYSTEM
        self.applications.lock(application)
        current = application.status
        if not self.allowed(current, target, role):
            raise InvalidTransition(current, target)
        application.status = target
        self.events.add(application.id, current.value, target.value,
                        actor.id if actor else None, role, note)
        self.db.commit()
        return application

    def system_advance(self, application_id: uuid.UUID, target: S, note: str | None = None) -> bool:
        """Move forward if the system may; otherwise do nothing. Safe to call twice."""
        application = self.applications.get_by_id(application_id)
        if application is None or not self.allowed(application.status, target, SYSTEM):
            return False
        try:
            self.move(application, target, note=note)
        except InvalidTransition:  # another request moved it first
            return False
        return True


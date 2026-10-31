import uuid

from sqlalchemy.orm import Session

from app.models.application import ApplicationStatus
from app.models.transcript import TranscriptEntry
from app.models.user import User, UserRole
from app.repositories.application import ApplicationRepository
from app.repositories.jobs import JobRepository
from app.repositories.transcript import TranscriptRepository
from app.schemas.transcript import TranscriptSave
from app.services.application import ApplicationNotFound

class TranscriptService:
    def __init__(self, db: Session):
        self.applications = ApplicationRepository(db)
        self.jobs = JobRepository(db)
        self.transcripts = TranscriptRepository(db)

    def save(self, application_id: uuid.UUID, data: TranscriptSave) -> int:
        application = self.applications.get_by_id(application_id)
        if application is None:
            raise ApplicationNotFound()

        entries = [(e.role, e.text) for e in data.entries]
        self.transcripts.replace_for_application(application_id, entries)

        spoke = any(role == "candidate" for role, _ in entries)
        if spoke and application.status == ApplicationStatus.submitted:
            self.applications.update_status(application, ApplicationStatus.interviewed)
        return len(entries)

    def read(self, application_id: uuid.UUID, user: User) -> list[TranscriptEntry]:
        application = self.applications.get_by_id(application_id)
        if application is None:
            raise ApplicationNotFound()

        if user.role == UserRole.candidate:
            allowed = application.candidate_id == user.id
        else:
            job = self.jobs.get_by_id(application.job_id)
            allowed = job is not None and job.employer_id == user.id
        if not allowed:
            raise ApplicationNotFound()

        return self.transcripts.list_by_application(application_id)
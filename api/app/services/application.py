
import uuid

from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.storage import save_resume
from app.core.parsing import extract_text
from app.models.application import Application
from app.models.user import User
from app.repositories.application import ApplicationRepository
from app.repositories.jobs import JobRepository


class JobNotFound(Exception):
    pass


class AlreadyApplied(Exception):
    pass


class ApplicationNotFound(Exception):
    pass


class NotJobOwner(Exception):
    pass


class ApplicationService:
    def __init__(self, db: Session):
        self.db = db
        self.applications = ApplicationRepository(db)
        self.jobs = JobRepository(db)

    def apply(self, candidate: User, job_id: uuid.UUID, resume: UploadFile) -> Application:
        '''
        checks the job exists and is open, blocks duplicates, saves the PDF, and creates the application 
        row for the logged-in candidate.
        '''
        job = self.jobs.get_by_id(job_id)
        if job is None or not job.is_active:
            raise JobNotFound()
        if self.applications.get_by_job_and_candidate(job_id, candidate.id):
            raise AlreadyApplied()

        filename = save_resume(resume)
        text = extract_text(filename)
        try:
            return self.applications.create(job_id, candidate.id, filename, text)
        except IntegrityError:
            self.db.rollback()
            raise AlreadyApplied()

    def list_mine(self, candidate: User) -> list[Application]:
        return self.applications.list_by_candidate(candidate.id)

    def list_for_job(self, job_id: uuid.UUID, employer: User) -> list[Application]:
        job = self.jobs.get_by_id(job_id)
        if job is None:
            raise JobNotFound()
        if job.employer_id != employer.id:
            raise NotJobOwner()
        return self.applications.list_by_job(job_id)


    def get_for_candidate(self, application_id: uuid.UUID, candidate: User) -> Application:
        '''
        loads an application by id and returns it only if it belongs to the logged-in candidate, 
        otherwise it raises ApplicationNotFound, so a candidate can never get a token for someone 
        else's application.
        
        '''
        application = self.applications.get_by_id(application_id)
        if application is None or application.candidate_id != candidate.id:
            raise ApplicationNotFound()
        return application
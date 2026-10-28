import uuid
from sqlalchemy.orm import Session
from app.models.job import Job
from app.models.user import User
from app.repositories.jobs import JobRepository
from app.schemas.job import JobCreate, JobUpdate



class JobNotFound(Exception):
    pass


class NotJobOwner(Exception):
    pass


class JobService:
    """builds a JobRepository from the given database session so the service can reach job data."""
    def __init__(self, db: Session):
        self.jobs = JobRepository(db)

    def create(self, employer: User, data: JobCreate) -> Job:
        '''
        saves a new job for the logged-in employer, taking employer_id from the user(logged in person) and never from 
        the request body.
        '''
        return self.jobs.create(
            employer_id=employer.id,
            title=data.title,
            description=data.description,
            location=data.location,
            employment_type=data.employment_type,
        )


    def get(self, job_id: uuid.UUID, user: User) -> Job:
        '''
        returns one job by id, but hides a closed job from everyone except its owner (they get “not found”).
        '''
        job = self.jobs.get_by_id(job_id)
        if job is None:
            raise JobNotFound()
        if not job.is_active and job.employer_id != user.id:
            raise JobNotFound()
        return job

    def list_active(self) -> list[Job]:
        '''returns all open jobs for candidates to browse.'''
        return self.jobs.list_active()

    def list_mine(self, employer: User) -> list[Job]:
        '''returns every job the given employer posted, open and closed.'''
        return self.jobs.list_by_employer(employer.id)

    def update(self, job_id: uuid.UUID, employer: User, data: JobUpdate) -> Job:
        '''checks the employer owns the job, then changes only the fields the client actually sent.'''
        job = self._get_owned(job_id, employer)
        changes = data.model_dump(exclude_unset=True)
        return self.jobs.update(job, **changes)

    def close(self, job_id: uuid.UUID, employer: User) -> Job:
        '''checks ownership, then soft-deletes the job by setting is_active=False.'''
        job = self._get_owned(job_id, employer)
        return self.jobs.update(job, is_active=False)

    def _get_owned(self, job_id: uuid.UUID, employer: User) -> Job:
        '''loads a job and raises JobNotFound if it’s missing or NotJobOwner if it belongs to another employer.'''
        job = self.jobs.get_by_id(job_id)
        if job is None:
            raise JobNotFound()
        if job.employer_id != employer.id:
            raise NotJobOwner()
        return job


#! What rules it holds ??

'''
=>Who owns a job: create takes the employer from the logged-in user, never from the request body.
=>Who may edit or close it: _get_owned checks job.employer_id == employer.id. Employer B can't touch 
  employer A's job.
=>Who may see it: a closed job is visible only to its owner. Everyone else gets “not found”.
=>What may change: update applies only the fields the client actually sent.
=>What “delete” means: close is a soft delete (is_active=False), not a real delete.

'''
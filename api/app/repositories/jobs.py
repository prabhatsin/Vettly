import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.job import EmploymentType, Job


class JobRepository:
    """All database access for jobs: create, get, list, update, close."""

    def __init__(self, db: Session):
        self.db = db

    # This step creates a row inside the jobs table 
    # migrations (Alembic) create or change tables
    def create(self,employer_id: uuid.UUID,title: str,description: str,location: str | None,employment_type: EmploymentType,) -> Job:
        """inserts one new job row for an employer and returns it with its generated id and timestamps. """
        job = Job(
            employer_id=employer_id,
            title=title,
            description=description,
            location=location,
            employment_type=employment_type,
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def get_by_id(self, job_id: uuid.UUID) -> Job | None:
        """fetches a single job by its primary key, or None if it doesn’t exist."""
        return self.db.get(Job, job_id)

    def list_active(self) -> list[Job]:
        """returns all open jobs (is_active = true), newest first, for candidates to browse."""
        stmt = select(Job).where(Job.is_active.is_(True)).order_by(Job.created_at.desc())
        return list(self.db.scalars(stmt))

    def list_by_employer(self, employer_id: uuid.UUID) -> list[Job]:
        """returns every job one employer posted, open and closed, newest first."""
        stmt = (
            select(Job)
            .where(Job.employer_id == employer_id)
            .order_by(Job.created_at.desc())
        )
        return list(self.db.scalars(stmt))

    def update(self, job: Job, **fields) -> Job:
        """
        update takes an existing job row and a set of changed values (like title="Senior Python Developer" 
        or is_active=False), overwrites only those columns on that one row, saves it to the database, and 
        returns the refreshed job, without ever changing the table’s structure.  sorter
        """
        for key, value in fields.items():
            setattr(job, key, value)
        self.db.commit()
        self.db.refresh(job)
        return job


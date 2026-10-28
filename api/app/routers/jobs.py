import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.user import User, UserRole
from app.schemas.job import JobCreate, JobResponse, JobUpdate
from app.services.job import JobNotFound, JobService, NotJobOwner

router = APIRouter(prefix="/jobs", tags=["jobs"])

not_found = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
not_owner = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN, detail="You do not own this job"
)


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
def create_job(
    data: JobCreate,
    employer: User = Depends(require_role(UserRole.employer)),
    db: Session = Depends(get_db),
):
    return JobService(db).create(employer, data)


@router.get("", response_model=list[JobResponse])
def list_jobs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return JobService(db).list_active()


@router.get("/mine", response_model=list[JobResponse])
def list_my_jobs(
    employer: User = Depends(require_role(UserRole.employer)),
    db: Session = Depends(get_db),
):
    return JobService(db).list_mine(employer)


@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return JobService(db).get(job_id, user)
    except JobNotFound:
        raise not_found


@router.put("/{job_id}", response_model=JobResponse)
def update_job(
    job_id: uuid.UUID,
    data: JobUpdate,
    employer: User = Depends(require_role(UserRole.employer)),
    db: Session = Depends(get_db),
):
    try:
        return JobService(db).update(job_id, employer, data)
    except JobNotFound:
        raise not_found
    except NotJobOwner:
        raise not_owner


@router.delete("/{job_id}", response_model=JobResponse)
def close_job(
    job_id: uuid.UUID,
    employer: User = Depends(require_role(UserRole.employer)),
    db: Session = Depends(get_db),
):
    try:
        return JobService(db).close(job_id, employer)
    except JobNotFound:
        raise not_found
    except NotJobOwner:
        raise not_owner
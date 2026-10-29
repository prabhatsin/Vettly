import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.core.storage import InvalidResume
from app.db.session import get_db
from app.models.user import User, UserRole
from app.schemas.application import ApplicationResponse
from app.services.application import (
    AlreadyApplied,
    ApplicationService,
    JobNotFound,
    NotJobOwner,
)

router = APIRouter(tags=["applications"])


@router.post(
    "/jobs/{job_id}/apply",
    response_model=ApplicationResponse,
    status_code=status.HTTP_201_CREATED,
)
def apply_to_job(
    job_id: uuid.UUID,
    resume: UploadFile = File(...),
    candidate: User = Depends(require_role(UserRole.candidate)),
    db: Session = Depends(get_db),
):
    try:
        return ApplicationService(db).apply(candidate, job_id, resume)
    except JobNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    except AlreadyApplied:
        raise HTTPException(status.HTTP_409_CONFLICT, "You already applied to this job")
    except InvalidResume as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.get("/applications/mine", response_model=list[ApplicationResponse])
def my_applications(
    candidate: User = Depends(require_role(UserRole.candidate)),
    db: Session = Depends(get_db),
):
    return ApplicationService(db).list_mine(candidate)


@router.get("/jobs/{job_id}/applications", response_model=list[ApplicationResponse])
def job_applications(
    job_id: uuid.UUID,
    employer: User = Depends(require_role(UserRole.employer)),
    db: Session = Depends(get_db),
):
    try:
        return ApplicationService(db).list_for_job(job_id, employer)
    except JobNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    except NotJobOwner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not own this job")
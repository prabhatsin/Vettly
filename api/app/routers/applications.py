import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.core.storage import InvalidResume
from app.db.session import get_db
from app.models.user import User, UserRole
from app.schemas.application import ApplicationResponse,ApplicantResponse , InterviewTokenResponse
from app.services.application import (AlreadyApplied,ApplicationService,JobNotFound,
    NotJobOwner, ApplicationNotFound
)

from app.config import settings
from app.core.livekit import create_room_token, room_name_for


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


@router.get("/jobs/{job_id}/applications", response_model=list[ApplicantResponse])
def job_applications(
    job_id: uuid.UUID,
    employer: User = Depends(require_role(UserRole.employer)),
    db: Session = Depends(get_db),
):
    try:
        rows = ApplicationService(db).list_for_job(job_id, employer)
        return [
            ApplicantResponse(
                **ApplicationResponse.model_validate(a).model_dump(),
                candidate_email=email,
            )
            for a, email in rows
        ]
    except JobNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    except NotJobOwner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not own this job")



@router.post(
    "/applications/{application_id}/interview-token",
    response_model=InterviewTokenResponse,
)
def interview_token(
    application_id: uuid.UUID,
    candidate: User = Depends(require_role(UserRole.candidate)),
    db: Session = Depends(get_db),
):
    try:
        application = ApplicationService(db).get_for_candidate(application_id, candidate)
    except ApplicationNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")

    room = room_name_for(application.id)
    token = create_room_token(str(candidate.id), candidate.email, room)
    return InterviewTokenResponse(token=token, url=settings.livekit_url, room=room)
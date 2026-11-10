import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models.user import User, UserRole
from app.schemas.employer import (
    CandidateRow,
    ReplayOut,
    ReportOut,
    RubricIn,
    RubricOut,
)
from app.schemas.scoring import Report
from app.services.employer import EmployerService, NotFound
from app.services.scoring_queue import ScoringQueue

logger = logging.getLogger("employer")
router = APIRouter(prefix="/employer", tags=["employer"])
employer_only = require_role(UserRole.employer)


def get_scoring_enqueue():
    return ScoringQueue().enqueue


def not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


@router.get("/jobs/{job_id}/candidates", response_model=list[CandidateRow])
def candidates(
    job_id: uuid.UUID, user: User = Depends(employer_only), db: Session = Depends(get_db)
):
    try:
        return EmployerService(db).candidates(job_id, user)
    except NotFound:
        raise not_found()


@router.get("/applications/{application_id}/report", response_model=ReportOut)
def report(
    application_id: uuid.UUID, user: User = Depends(employer_only), db: Session = Depends(get_db)
):
    try:
        row = EmployerService(db).report(application_id, user)
    except NotFound:
        raise not_found()
    return ReportOut(
        application_id=row.application_id,
        status=row.status,
        error=row.error,
        report=Report.model_validate(row.report) if row.report else None,
        updated_at=row.updated_at,
    )


@router.get("/applications/{application_id}/replay", response_model=ReplayOut)
def replay(
    application_id: uuid.UUID, user: User = Depends(employer_only), db: Session = Depends(get_db)
):
    try:
        return EmployerService(db).replay(application_id, user)
    except NotFound:
        raise not_found()


@router.post("/applications/{application_id}/rescore", status_code=status.HTTP_202_ACCEPTED)
def rescore(
    application_id: uuid.UUID,
    user: User = Depends(employer_only),
    db: Session = Depends(get_db),
    enqueue=Depends(get_scoring_enqueue),
):
    try:
        EmployerService(db).own_application(application_id, user)
    except NotFound:
        raise not_found()
    enqueue(str(application_id))
    return {"queued": True}


@router.get("/jobs/{job_id}/rubric", response_model=RubricOut)
def get_rubric(
    job_id: uuid.UUID, user: User = Depends(employer_only), db: Session = Depends(get_db)
):
    try:
        return EmployerService(db).get_rubric(job_id, user)
    except NotFound:
        raise not_found()


@router.put("/jobs/{job_id}/rubric", response_model=RubricOut)
def put_rubric(
    job_id: uuid.UUID,
    data: RubricIn,
    user: User = Depends(employer_only),
    db: Session = Depends(get_db),
):
    try:
        return EmployerService(db).set_rubric(job_id, user, data.criteria)
    except NotFound:
        raise not_found()

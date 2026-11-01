import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.routers.transcripts import require_internal_key
from app.schemas.plan import PlanResponse
from app.services.application import ApplicationNotFound
from app.services.plan import PlanService
from app.services.plan_generator import PlanGenerationFailed, PlanGenerator

router = APIRouter(tags=["plans"])


def get_plan_generator() -> PlanGenerator:
    return PlanGenerator()


@router.post(
    "/internal/applications/{application_id}/plan",
    response_model=PlanResponse,
    dependencies=[Depends(require_internal_key)],
)
def get_or_create_plan(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    generator: PlanGenerator = Depends(get_plan_generator),
):
    try:
        ctx = PlanService(db, generator).get_or_create(application_id)
    except ApplicationNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    except PlanGenerationFailed:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Could not generate a plan")
    return PlanResponse(
        application_id=ctx.plan.application_id,
        job_title=ctx.job_title,
        job_description=ctx.job_description,
        resume_excerpt=ctx.resume_excerpt,
        questions=ctx.plan.plan["questions"],
    )
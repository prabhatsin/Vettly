import logging
import uuid

from app.db.session import SessionLocal
from app.services.plan import PlanService
from app.services.plan_generator import PlanGenerator

logger = logging.getLogger("plan_prewarm")


def prewarm_plan(application_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        PlanService(db, PlanGenerator()).get_or_create(application_id)
    except Exception:
        logger.exception("plan pre-generation failed for %s", application_id)
    finally:
        db.close()
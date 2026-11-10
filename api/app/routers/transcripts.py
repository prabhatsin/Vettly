import logging
import secrets
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.config import settings
from app.db.session import get_db
from app.models.user import User
from app.routers.employer import get_scoring_enqueue
from app.schemas.transcript import TranscriptEntryOut, TranscriptSave
from app.services.application import ApplicationNotFound
from app.services.transcript import TranscriptService

logger = logging.getLogger("transcripts")
router = APIRouter(tags=["transcripts"])


def require_internal_key(x_internal_key: str = Header(default="")):
    ok = secrets.compare_digest(
        x_internal_key.encode(), settings.internal_api_key.encode()
    )
    if not ok:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid internal key")


@router.post(
    "/internal/applications/{application_id}/transcript",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_internal_key)],
)
def save_transcript(
    application_id: uuid.UUID,
    data: TranscriptSave,
    db: Session = Depends(get_db),
    enqueue=Depends(get_scoring_enqueue),
):
    try:
        count = TranscriptService(db).save(application_id, data)
    except ApplicationNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")

    # Only a finished interview is scored. A failed queue must not lose the transcript.
    if data.ended:
        try:
            enqueue(str(application_id))
        except Exception:
            logger.exception("could not queue scoring for %s", application_id)
    return {"saved": count}


@router.get(
    "/applications/{application_id}/transcript",
    response_model=list[TranscriptEntryOut],
)
def read_transcript(
    application_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return TranscriptService(db).read(application_id, user)
    except ApplicationNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")

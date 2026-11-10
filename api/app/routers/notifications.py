import uuid

import jwt
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.config import settings
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User
from app.schemas.notification import NotificationOut
from app.services.notifications import NotificationNotFound, NotificationService

router = APIRouter(tags=["notifications"])


@router.get("/notifications", response_model=list[NotificationOut])
def my_notifications(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return NotificationService(db).list_mine(user)


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: uuid.UUID, user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    try:
        return NotificationService(db).mark_read(notification_id, user)
    except NotificationNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


@router.get("/events/stream")
async def event_stream(request: Request, token: str):
    """Server-sent events. Token is a query param because EventSource can't send headers."""
    try:
        user_id = uuid.UUID(decode_access_token(token)["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    async def gen():
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        pubsub = r.pubsub()
        await pubsub.subscribe(f"user:{user_id}")
        try:
            yield ": connected\n\n"
            while not await request.is_disconnected():
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15.0)
                yield f"data: {msg['data']}\n\n" if msg else ": ping\n\n"
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()
            await r.aclose()

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core import fake_payments
from app.db.session import get_db
from app.services.payments import PaymentService

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/payments")
async def payment_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()  # raw bytes: the signature is over exactly these
    if not fake_payments.verify(body, request.headers.get(fake_payments.SIGNATURE_HEADER)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Bad signature")
    try:
        event = json.loads(body)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Bad payload")
    await run_in_threadpool(PaymentService(db).handle_event, event)
    return {"received": True}
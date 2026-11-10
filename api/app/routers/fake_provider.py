from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends

from app.core import fake_payments

router = APIRouter(prefix="/fake-provider", tags=["fake-provider"])


def get_webhook_sender():
    return fake_payments.send_webhook


@router.post("/intents/{intent_id}/confirm", status_code=202)
def confirm(
    intent_id: str,
    background: BackgroundTasks,
    outcome: Literal["succeeded", "failed"] = "succeeded",
    send=Depends(get_webhook_sender),
):
    """What the provider's checkout page does on 'Pay'. Our API learns the result only via the webhook."""
    background.add_task(send, fake_payments.event_body(intent_id, outcome == "succeeded"))
    return {"status": "processing"}
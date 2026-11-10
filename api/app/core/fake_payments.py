"""Stand-in for Stripe test mode: intents, idempotency keys, signed webhooks."""
import hashlib
import hmac
import json
import logging
import time
import uuid

import httpx

from app.config import settings

logger = logging.getLogger("uvicorn.error")
SIGNATURE_HEADER = "X-Fake-Signature"


def create_intent(amount: int, currency: str, idempotency_key: str, metadata: dict) -> str:
    """Same key gives the same intent id, like a real provider's idempotency."""
    return "pi_fake_" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:24]


def sign(body: bytes) -> str:
    return hmac.new(settings.payment_webhook_secret.encode(), body, hashlib.sha256).hexdigest()


def verify(body: bytes, signature: str | None) -> bool:
    return bool(signature) and hmac.compare_digest(sign(body), signature)


def event_body(intent_id: str, succeeded: bool = True) -> bytes:
    kind = "payment_intent.succeeded" if succeeded else "payment_intent.payment_failed"
    return json.dumps(
        {"id": f"evt_{uuid.uuid4().hex[:16]}", "type": kind, "data": {"intent_id": intent_id}}
    ).encode()


def send_webhook(body: bytes) -> None:
    url = f"{settings.api_base_url}/webhooks/payments"
    headers = {SIGNATURE_HEADER: sign(body), "Content-Type": "application/json"}
    for attempt in range(3):
        try:
            if httpx.post(url, content=body, headers=headers, timeout=5).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1 + attempt)
    logger.warning("fake provider: webhook delivery failed")
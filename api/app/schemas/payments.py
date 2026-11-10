import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, computed_field


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    offer_id: uuid.UUID
    amount: int
    currency: str
    status: str
    provider_intent_id: str | None
    created_at: datetime

    @computed_field
    @property
    def checkout_url(self) -> str | None:
        if self.status == "pending" and self.provider_intent_id:
            return f"/pay/{self.provider_intent_id}"
        return None
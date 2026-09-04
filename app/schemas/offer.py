import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

Channel = Literal["sms", "whatsapp"]
RecipientStatus = Literal["pending", "sent", "failed", "blocked"]


class OfferSendCreate(BaseModel):
    message: str = Field(min_length=1)
    customer_ids: list[uuid.UUID] = Field(min_length=1)
    channel: Channel = "sms"
    template_used: str | None = None


class OfferSendRecipientOut(ORMModel):
    offer_customer_id: uuid.UUID
    customer_name: str
    status: RecipientStatus
    provider_response: str | None = None
    sent_at: datetime | None = None


class OfferSendOut(ORMModel):
    id: uuid.UUID
    message: str
    channel: Channel
    template_used: str | None = None
    sent_at: datetime
    recipients: list[OfferSendRecipientOut] = []
    # Computed in the service layer from the already eager-loaded recipients
    # (no extra query) — the counts the history view's summary chips need,
    # without making the frontend re-derive them from the full list every time.
    status_counts: dict[str, int] = {}
    created_by: uuid.UUID | None = None
    created_by_name: str | None = None

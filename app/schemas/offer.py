import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class OfferSendCreate(BaseModel):
    message: str = Field(min_length=1)
    customer_ids: list[uuid.UUID] = Field(min_length=1)


class OfferSendRecipientOut(ORMModel):
    customer_id: uuid.UUID
    customer_name: str


class OfferSendOut(ORMModel):
    id: uuid.UUID
    message: str
    sent_at: datetime
    recipients: list[OfferSendRecipientOut] = []
    created_by: uuid.UUID | None = None
    created_by_name: str | None = None

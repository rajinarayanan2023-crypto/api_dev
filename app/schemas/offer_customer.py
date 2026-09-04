import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class OfferCustomerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=20)


class OfferCustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=20)
    active: bool | None = None


class OfferCustomerOut(ORMModel):
    id: uuid.UUID
    name: str
    phone: str | None = None
    active: bool
    created_at: datetime
    updated_at: datetime

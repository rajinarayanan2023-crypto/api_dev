import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMModel


class StationBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    brand: str | None = Field(default=None, max_length=100)
    dealer_type: str | None = Field(default=None, max_length=100)
    sap_no: str | None = Field(default=None, max_length=50)
    gstin: str | None = Field(default=None, max_length=20)
    dealer_name: str | None = Field(default=None, max_length=255)
    address_lines: list[str] | None = None
    location: str | None = Field(default=None, max_length=255)
    mobiles: list[str] | None = None
    email: EmailStr | None = None
    logo_url: str | None = Field(default=None, max_length=500)
    photo_url: str | None = Field(default=None, max_length=500)
    audit_contact_email: EmailStr | None = None


class StationUpdate(StationBase):
    name: str | None = Field(default=None, min_length=1, max_length=255)


class StationOut(StationBase, ORMModel):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None = None
    created_by_name: str | None = None
    updated_by: uuid.UUID | None = None
    updated_by_name: str | None = None

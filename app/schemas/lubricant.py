import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

Packaging = Literal["packet", "cane"]


class PriceHistoryCreate(BaseModel):
    effective_from: date
    rate: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


class PriceHistoryOut(ORMModel):
    id: uuid.UUID
    effective_from: date
    rate: Decimal


class PurchaseCreate(BaseModel):
    date: date
    qty: int = Field(gt=0)
    cost: Decimal = Field(ge=0, max_digits=10, decimal_places=2)


class PurchaseOut(ORMModel):
    id: uuid.UUID
    date: date
    qty: int
    cost: Decimal


class LubricantBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    unit: str = Field(default="Pcs", max_length=50)
    packaging: Packaging = "packet"


class LubricantCreate(LubricantBase):
    opening_rate: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    opening_stock: int = Field(default=0, ge=0)


class LubricantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    unit: str | None = Field(default=None, max_length=50)
    packaging: Packaging | None = None


class LubricantOut(LubricantBase, ORMModel):
    id: uuid.UUID
    stock: Decimal
    price_history: list[PriceHistoryOut] = []
    purchase_history: list[PurchaseOut] = []
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None = None
    created_by_name: str | None = None
    updated_by: uuid.UUID | None = None
    updated_by_name: str | None = None

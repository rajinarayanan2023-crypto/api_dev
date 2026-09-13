import uuid
from datetime import date, datetime
# Aliased for PurchaseUpdate's `date` field below — `date: date | None = ...`
# breaks at class-definition time: Python binds the field's default value to
# the name `date` in the class namespace BEFORE evaluating that same line's
# `date | None` annotation, so the annotation resolves against `None`
# instead of the datetime class, raising "unsupported operand type(s) for
# |: 'NoneType' and 'NoneType'". Only a field literally named `date` with a
# default hits this; the alias sidesteps it entirely.
from datetime import date as _date
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


# Correcting a mis-entered purchase — qty stays a whole int (never a
# fraction, same as PurchaseCreate above); LubricantService.update_purchase
# is what actually blocks a correction that would drive stock negative.
class PurchaseUpdate(BaseModel):
    date: _date | None = None
    qty: int | None = Field(default=None, gt=0)
    cost: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)


class PurchaseOut(ORMModel):
    id: uuid.UUID
    date: date
    qty: int
    cost: Decimal


class SoldHistoryEntryOut(BaseModel):
    """One Fuel Entry oil row that sold this product — only ever sourced
    from a 'final' shift entry (a draft's rows aren't a real sale yet)."""

    fuel_entry_id: uuid.UUID
    date: date
    pump_key: str
    shift_number: int
    row_type: Literal["pocket", "cane"]
    qty: Decimal
    rate: Decimal
    amount: Decimal


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
    # Set by LubricantService from a separate aggregate query (see
    # get_sales_summary) — not a real column on LubricantProduct, so both
    # default to None/0 for a product that's never sold a unit.
    last_sold_date: date | None = None
    total_sold: Decimal = Decimal("0")
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None = None
    created_by_name: str | None = None
    updated_by: uuid.UUID | None = None
    updated_by_name: str | None = None

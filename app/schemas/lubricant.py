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

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel

Packaging = Literal["packet", "cane"]

# A plausibility floor, not a real business rule — same reasoning as
# expense.py's _EARLIEST_SANE_EXPENSE_DATE, just here to catch an obvious
# typo (e.g. 1920 instead of 2020) at entry time.
_EARLIEST_SANE_LUBRICANT_DATE = _date(1970, 1, 1)


def _validate_purchase_date(value: _date | None) -> _date | None:
    if value is None:
        return None
    if value > _date.today():
        raise ValueError("Purchase date cannot be in the future")
    if value < _EARLIEST_SANE_LUBRICANT_DATE:
        raise ValueError(f"Purchase date cannot be before {_EARLIEST_SANE_LUBRICANT_DATE.isoformat()}")
    return value


class PurchaseCreate(BaseModel):
    date: date
    qty: int = Field(gt=0)
    cost: Decimal = Field(ge=0, max_digits=10, decimal_places=2)

    _validate_date = field_validator("date")(_validate_purchase_date)


# Correcting a mis-entered purchase — qty stays a whole int (never a
# fraction, same as PurchaseCreate above); LubricantService.update_purchase
# is what actually blocks a correction that would drive stock negative.
class PurchaseUpdate(BaseModel):
    date: _date | None = None
    qty: int | None = Field(default=None, gt=0)
    cost: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)

    _validate_date = field_validator("date")(_validate_purchase_date)


class PurchaseOut(ORMModel):
    id: uuid.UUID
    date: date
    qty: int
    cost: Decimal
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None = None
    created_by_name: str | None = None
    updated_by: uuid.UUID | None = None
    updated_by_name: str | None = None


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
    # Also doubles as the opening stock's acquisition cost (see
    # LubricantService.create_product) — there's no separate "what did you
    # pay for the opening stock" field, so this is the only real figure
    # available to seed the product's first purchase_history row.
    opening_rate: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    opening_stock: int = Field(default=0, ge=0)


class LubricantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    unit: str | None = Field(default=None, max_length=50)
    packaging: Packaging | None = None


class LubricantOut(LubricantBase, ORMModel):
    id: uuid.UUID
    stock: Decimal
    purchase_history: list[PurchaseOut] = []
    # Set by LubricantService from a separate aggregate query (see
    # get_sales_summary) — not a real column on LubricantProduct, so both
    # default to None/0 for a product that's never sold a unit.
    last_sold_date: date | None = None
    total_sold: Decimal = Decimal("0")
    # Also set by LubricantService (see get_sold_count_by_rate) — units
    # already sold through a final Pump 2 oil row, broken down by the exact
    # cost they were sold at (keyed as a string; Decimal isn't a valid JSON
    # object key). Lets the Fuel Entry oil-row picker's "Available" figure
    # for one specific cost actually subtract what's already gone from that
    # cost's own batch, instead of only capping against the product's one
    # aggregate running stock — see utils/lubricants.js's
    # availableAtCostBreakdown.
    sold_count_by_rate: dict[str, Decimal] = {}
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None = None
    created_by_name: str | None = None
    updated_by: uuid.UUID | None = None
    updated_by_name: str | None = None

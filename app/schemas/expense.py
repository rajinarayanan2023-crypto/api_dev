import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel

# A plausibility floor, not a real business rule — same reasoning as
# employee.py's _EARLIEST_SANE_JOIN_DATE, just here to catch an obvious typo
# (e.g. 1920 instead of 2020) at entry time.
_EARLIEST_SANE_EXPENSE_DATE = date(1970, 1, 1)


def _validate_expense_date(value: date) -> date:
    if value > date.today():
        raise ValueError("Expense date cannot be in the future")
    if value < _EARLIEST_SANE_EXPENSE_DATE:
        raise ValueError(f"Expense date cannot be before {_EARLIEST_SANE_EXPENSE_DATE.isoformat()}")
    return value


class ExpenseItemCreate(BaseModel):
    label: str = Field(min_length=1, max_length=255)
    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


class ExpenseItemOut(ORMModel):
    id: uuid.UUID
    label: str
    amount: Decimal


class ExpenseDayCreate(BaseModel):
    date: date
    items: list[ExpenseItemCreate] = Field(min_length=1)

    _validate_date = field_validator("date")(_validate_expense_date)


class ExpenseDayUpdate(BaseModel):
    """Full replace, matching the UI: the whole item list is resubmitted on
    every save rather than incremental add/remove patches."""

    date: date
    items: list[ExpenseItemCreate] = Field(min_length=1)

    _validate_date = field_validator("date")(_validate_expense_date)


class ExpenseDayOut(ORMModel):
    id: uuid.UUID
    date: date
    items: list[ExpenseItemOut] = []
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None = None
    created_by_name: str | None = None
    updated_by: uuid.UUID | None = None
    updated_by_name: str | None = None

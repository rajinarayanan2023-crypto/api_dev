import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


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


class ExpenseDayUpdate(BaseModel):
    """Full replace, matching the UI: the whole item list is resubmitted on
    every save rather than incremental add/remove patches."""

    date: date
    items: list[ExpenseItemCreate] = Field(min_length=1)


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

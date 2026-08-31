import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class SalaryHistoryCreate(BaseModel):
    effective_from: date
    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


class SalaryHistoryOut(ORMModel):
    id: uuid.UUID
    effective_from: date
    amount: Decimal


class EmployeeBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    father_name: str | None = Field(default=None, max_length=255)
    role: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=20)
    join_date: date
    active: bool = True
    notes: str | None = None


class EmployeeCreate(EmployeeBase):
    starting_salary: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


class EmployeeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    father_name: str | None = Field(default=None, max_length=255)
    role: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=20)
    join_date: date | None = None
    active: bool | None = None
    notes: str | None = None


class EmployeeCreditOut(ORMModel):
    """Written by Fuel Entry when a shift records an 'employee credit'
    payment line (fuel/oil taken on credit, settled against pay) — read-only
    here, no direct create/update/delete endpoint for this alone.
    """

    id: uuid.UUID
    date: date
    amount: Decimal
    note: str | None = None
    source_fuel_entry_id: uuid.UUID | None = None
    created_at: datetime


class EmployeeOut(EmployeeBase, ORMModel):
    id: uuid.UUID
    salary_history: list[SalaryHistoryOut] = []
    credits: list[EmployeeCreditOut] = []
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None = None
    created_by_name: str | None = None
    updated_by: uuid.UUID | None = None
    updated_by_name: str | None = None

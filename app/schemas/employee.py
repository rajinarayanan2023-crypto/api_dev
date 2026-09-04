import re
import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel

# A field literally named `date` typed `date | None = None` self-collides:
# Python stores the `None` default under the class's `date` name before it
# evaluates the `date | None` annotation on that same line, so the
# annotation sees `None | None` instead of the imported type. This alias
# sidesteps it (see EmployeeCreditUpdate below).
_DateType = date


def validate_phone(phone: str | None) -> str | None:
    if phone is not None and not re.fullmatch(r"\d{10}", phone):
        raise ValueError("Phone number must be exactly 10 digits")
    return phone


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

    _check_phone = field_validator("phone")(validate_phone)


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

    _check_phone = field_validator("phone")(validate_phone)


class EmployeeCreditCreate(BaseModel):
    date: date
    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    note: str | None = None


class EmployeeCreditUpdate(BaseModel):
    date: _DateType | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    note: str | None = None


class EmployeeCreditOut(ORMModel):
    """Written either by hand (the standalone Employee Credits screen — see
    add_credit/update_credit/delete_credit) or by Fuel Entry when a shift
    records an 'employee credit' payment line (fuel/oil taken on credit,
    settled against pay). A row from Fuel Entry has source_fuel_entry_id set
    and can't be edited/removed directly here — that stays tied to deleting
    the fuel entry itself.
    """

    id: uuid.UUID
    date: date
    amount: Decimal
    note: str | None = None
    source_fuel_entry_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None = None
    created_by_name: str | None = None
    updated_by: uuid.UUID | None = None
    updated_by_name: str | None = None


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

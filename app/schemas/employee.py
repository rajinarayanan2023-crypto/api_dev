import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

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


# A plausibility floor, not a real business rule — this app has no station
# older than this. Exists purely to catch an obvious typo (e.g. 1920 instead
# of 2020) at entry time: an employee's join_date is the starting point for
# both utils/salary.js's carryForwardBalance loop and Salary.jsx's attendance
# pre-loading effect, both of which walk forward month-by-month from it, so a
# century-off join_date would make the Salary page try to compute/fetch over
# a thousand months for that one employee on every load.
_EARLIEST_SANE_JOIN_DATE = date(1970, 1, 1)


def validate_join_date(value: date | None) -> date | None:
    if value is None:
        return value
    if value > date.today():
        raise ValueError("Join date cannot be in the future")
    if value < _EARLIEST_SANE_JOIN_DATE:
        raise ValueError(f"Join date cannot be before {_EARLIEST_SANE_JOIN_DATE.isoformat()}")
    return value


class SalaryHistoryCreate(BaseModel):
    effective_from: date
    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


class SalaryHistoryOut(ORMModel):
    id: uuid.UUID
    effective_from: date
    amount: Decimal
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None = None
    created_by_name: str | None = None
    updated_by: uuid.UUID | None = None
    updated_by_name: str | None = None


class SalaryPaymentCreate(BaseModel):
    period_year: int = Field(ge=2000, le=2100)
    period_month: int = Field(ge=1, le=12)
    amount_paid: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    # Whatever the live "payable" figure showed on screen at the moment this
    # payment was recorded — a snapshot, never recomputed server-side (see
    # SalaryPayment's own docstring). Optional since a backfilled historical
    # payment may have no such figure to attach.
    payable_snapshot: Decimal | None = Field(default=None, max_digits=10, decimal_places=2)
    paid_date: date
    note: str | None = None


class SalaryPaymentUpdate(BaseModel):
    period_year: int | None = Field(default=None, ge=2000, le=2100)
    period_month: int | None = Field(default=None, ge=1, le=12)
    amount_paid: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    paid_date: _DateType | None = None
    note: str | None = None


class SalaryPaymentOut(ORMModel):
    id: uuid.UUID
    period_year: int
    period_month: int
    amount_paid: Decimal
    payable_snapshot: Decimal | None = None
    paid_date: date
    note: str | None = None
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None = None
    created_by_name: str | None = None
    updated_by: uuid.UUID | None = None
    updated_by_name: str | None = None


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
    # Overrides EmployeeBase's optional father_name — required for a NEW
    # employee. Left optional on EmployeeBase/EmployeeOut instead of tightened
    # there too, since at least one existing employee predates this rule and
    # still has none on file; EmployeeOut has to keep serializing that row.
    father_name: str = Field(min_length=1, max_length=255)
    starting_salary: Decimal = Field(gt=0, max_digits=10, decimal_places=2)

    # Same reasoning as father_name just above: this belongs on EmployeeCreate
    # only, never on EmployeeBase — EmployeeOut inherits EmployeeBase too, and
    # a join_date sanity rule added *after* some employees already exist must
    # never block reading those existing (now "invalid") rows back out.
    _check_join_date = field_validator("join_date")(validate_join_date)


class EmployeeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    # Still omittable (a partial update that doesn't touch this field), but
    # can't be sent as an empty string — this is what stops an existing
    # employee's father_name from being cleared back out once set.
    father_name: str | None = Field(default=None, min_length=1, max_length=255)
    role: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=20)
    join_date: date | None = None
    active: bool | None = None
    notes: str | None = None

    _check_phone = field_validator("phone")(validate_phone)
    _check_join_date = field_validator("join_date")(validate_join_date)


CreditType = Literal["credit", "repayment", "excess"]


class EmployeeCreditCreate(BaseModel):
    date: date
    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    type: CreditType = "credit"
    note: str | None = None


class EmployeeCreditUpdate(BaseModel):
    date: _DateType | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    type: CreditType | None = None
    note: str | None = None


class EmployeeCreditOut(ORMModel):
    """Written either by hand (the standalone Employee Credits screen — see
    add_credit/update_credit/delete_credit) or by Fuel Entry, which writes
    one of two kinds: an 'employee credit' payment line (fuel/oil taken on
    credit, settled against pay), or the shift's own cash shortage/excess
    tied to whoever worked it (see
    FuelEntryService._apply_shift_variance_credit). A row from Fuel Entry
    has source_fuel_entry_id set and can't be edited/removed directly here —
    that stays tied to editing/deleting the fuel entry itself.
    """

    id: uuid.UUID
    date: date
    amount: Decimal
    type: CreditType
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
    payments: list[SalaryPaymentOut] = []
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None = None
    created_by_name: str | None = None
    updated_by: uuid.UUID | None = None
    updated_by_name: str | None = None

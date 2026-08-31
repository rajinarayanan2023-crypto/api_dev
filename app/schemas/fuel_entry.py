import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

PumpKey = Literal["pump1", "pump2"]
ShiftNumber = Literal[1, 2, 3]
FuelKey = Literal["petrol", "diesel", "oil"]
PaymentType = Literal["cash", "credit", "employee_credit", "expense"]
OilRowType = Literal["pocket", "cane"]
EntryStatus = Literal["draft", "final"]


class FuelReadingIn(BaseModel):
    opening: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=3)
    closing: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=3)
    testing: Decimal = Field(default=Decimal("0"), ge=0, max_digits=10, decimal_places=3)
    rate: Decimal = Field(default=Decimal("0"), ge=0, max_digits=10, decimal_places=3)


class FuelNozzlesIn(BaseModel):
    nozzle1: FuelReadingIn
    nozzle2: FuelReadingIn


class FuelEntryOilRowIn(BaseModel):
    product_id: uuid.UUID | None = None
    stock_count: Decimal = Field(default=Decimal("0"), ge=0, max_digits=10, decimal_places=3)
    stock_rate: Decimal = Field(default=Decimal("0"), ge=0, max_digits=10, decimal_places=2)


class PaymentLineIn(BaseModel):
    label: str = ""
    amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    type: PaymentType = "cash"
    customer_id: uuid.UUID | None = None
    employee_id: uuid.UUID | None = None
    note: str | None = None


class FuelEntryBillIn(BaseModel):
    file_name: str
    file_url: str
    uploaded_date: date


# A shift entry is always resubmitted whole (readings, oil rows, payments,
# bills all replaced together) — same "full replace" pattern as ExpenseDay —
# so create and update share this one shape.
class FuelEntryWrite(BaseModel):
    date: date
    pump_key: PumpKey
    shift_number: ShiftNumber
    internal_only: bool = False
    employee_id: uuid.UUID | None = None
    status: EntryStatus = "draft"
    petrol: FuelNozzlesIn
    diesel: FuelNozzlesIn
    oil: FuelNozzlesIn | None = None
    oil_rows: list[FuelEntryOilRowIn] = []
    cane_oil_rows: list[FuelEntryOilRowIn] = []
    cane_oil_offer: Decimal = Field(default=Decimal("0"), ge=0, max_digits=10, decimal_places=2)
    payments: list[PaymentLineIn] = []
    bills: list[FuelEntryBillIn] = []
    notes: str | None = None


class FuelReadingOut(BaseModel):
    opening: Decimal
    closing: Decimal
    testing: Decimal
    rate: Decimal
    liters: Decimal
    amount: Decimal


class FuelNozzlesOut(BaseModel):
    nozzle1: FuelReadingOut
    nozzle2: FuelReadingOut


class FuelEntryOilRowOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID | None = None
    stock_count: Decimal
    stock_rate: Decimal
    amount: Decimal


class PaymentLineOut(BaseModel):
    id: uuid.UUID
    label: str
    amount: Decimal
    type: PaymentType
    customer_id: uuid.UUID | None = None
    employee_id: uuid.UUID | None = None
    note: str | None = None


class FuelEntryBillOut(BaseModel):
    id: uuid.UUID
    file_name: str
    file_url: str
    uploaded_date: date


class FuelEntryOut(ORMModel):
    id: uuid.UUID
    date: date
    pump_key: PumpKey
    shift_number: int
    internal_only: bool
    employee_id: uuid.UUID | None = None
    employee_name: str | None = None
    status: EntryStatus
    petrol: FuelNozzlesOut
    diesel: FuelNozzlesOut
    oil: FuelNozzlesOut | None = None
    oil_rows: list[FuelEntryOilRowOut] = []
    cane_oil_rows: list[FuelEntryOilRowOut] = []
    cane_oil_offer: Decimal
    payments: list[PaymentLineOut] = []
    bills: list[FuelEntryBillOut] = []
    notes: str | None = None
    # Server-computed, authoritative — mirrors ui/src/utils/fuelCalc.js's
    # shiftSaleAmount/shiftPaymentsTotal/shiftVariance exactly.
    total_sale_amount: Decimal
    total_payments: Decimal
    excess_shortage: Decimal
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None = None
    created_by_name: str | None = None
    updated_by: uuid.UUID | None = None
    updated_by_name: str | None = None

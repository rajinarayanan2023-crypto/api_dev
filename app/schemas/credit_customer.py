import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

LedgerType = Literal["credit", "payment"]
FuelType = Literal["petrol", "diesel", "oil"]


# file_url (here and on CreditLedgerEntryCreate/Out's bill_file_url) holds
# the R2 object KEY, not a resolvable URL — a presigned GET URL expires, so
# one is generated fresh on demand by GET /uploads/{key}/download-url
# instead of ever being stored. Fields kept named file_url/bill_file_url
# (not renamed) to avoid touching every caller that already reads/writes
# them — only what's stored in them changed.
class CreditCustomerBillIn(BaseModel):
    file_name: str
    file_url: str
    uploaded_date: date = Field(default_factory=date.today)


class CreditCustomerBillOut(ORMModel):
    id: uuid.UUID
    file_name: str
    file_url: str
    uploaded_date: date


class CreditLedgerEntryCreate(BaseModel):
    date: date
    type: LedgerType
    fuel_type: FuelType | None = None
    litres: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=3)
    rate: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=3)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    mode: str | None = None
    note: str | None = None
    bill_file_name: str | None = None
    bill_file_url: str | None = None


class CreditLedgerEntryOut(ORMModel):
    id: uuid.UUID
    date: date
    type: LedgerType
    fuel_type: str | None = None
    litres: Decimal | None = None
    rate: Decimal | None = None
    amount: Decimal
    mode: str | None = None
    note: str | None = None
    source_fuel_entry_id: uuid.UUID | None = None
    bill_file_name: str | None = None
    bill_file_url: str | None = None
    created_at: datetime


class CreditCustomerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=20)
    opening_balance: Decimal = Field(default=Decimal("0"), max_digits=12, decimal_places=2)
    notes: str | None = None
    bills: list[CreditCustomerBillIn] = []


class CreditCustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=20)
    opening_balance: Decimal | None = Field(default=None, max_digits=12, decimal_places=2)
    notes: str | None = None
    # Omit entirely to leave bills untouched; a full list (including []) fully
    # replaces the customer's bills — same "whole thing resubmitted" pattern
    # as Fuel Entry's bills, and matches exactly what the Credit Bills page
    # already sends (old bills + newly attached ones, or the list minus a
    # removed one).
    bills: list[CreditCustomerBillIn] | None = None


class CreditCustomerOut(ORMModel):
    id: uuid.UUID
    name: str
    phone: str | None = None
    opening_balance: Decimal
    notes: str | None = None
    # Server-computed — opening_balance + sum(credit) - sum(payment) —
    # mirrors ui/src/data/mockData.js's closingBalance() exactly. The
    # frontend keeps computing this itself from the ledger below (unchanged),
    # this is just the authoritative value alongside it.
    closing_balance: Decimal
    # Named to match the ORM relationship (CreditCustomer.ledger_entries) —
    # apiClient.js's normalizeCreditCustomer maps this to the frontend's
    # `ledger` key, matching ui/src/data/mockData.js's shape.
    ledger_entries: list[CreditLedgerEntryOut] = []
    bills: list[CreditCustomerBillOut] = []
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None = None
    created_by_name: str | None = None
    updated_by: uuid.UUID | None = None
    updated_by_name: str | None = None

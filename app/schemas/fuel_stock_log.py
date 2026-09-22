import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class FuelStockLogCreate(BaseModel):
    """Submitting the same (log_date, is_shift3) checkpoint again replaces
    that row rather than erroring — same correction pattern as fuel/
    commission rate history. See app/models/fuel_stock_log.py for why only
    these two figures (per fuel) are stored at all, and for what is_shift3
    distinguishes.
    """

    log_date: date
    is_shift3: bool = False
    petrol_opening_stock: Decimal = Field(ge=0, max_digits=12, decimal_places=3)
    petrol_stock_received: Decimal = Field(default=0, ge=0, max_digits=12, decimal_places=3)
    diesel_opening_stock: Decimal = Field(ge=0, max_digits=12, decimal_places=3)
    diesel_stock_received: Decimal = Field(default=0, ge=0, max_digits=12, decimal_places=3)


class FuelStockLogOut(ORMModel):
    id: uuid.UUID
    log_date: date
    is_shift3: bool
    petrol_opening_stock: Decimal
    petrol_stock_received: Decimal
    diesel_opening_stock: Decimal
    diesel_stock_received: Decimal
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None = None
    created_by_name: str | None = None
    updated_by: uuid.UUID | None = None
    updated_by_name: str | None = None

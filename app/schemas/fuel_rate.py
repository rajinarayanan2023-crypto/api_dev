import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class FuelRateCreate(BaseModel):
    """Submitting the same effective_from again replaces that revision
    rather than erroring — this is also how a mistyped rate gets corrected:
    save the same date again with the right numbers. See app/models/fuel_rate.py.
    """

    effective_from: date
    petrol: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    diesel: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    oil: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


class FuelRateOut(ORMModel):
    id: uuid.UUID
    effective_from: date
    petrol: Decimal
    diesel: Decimal
    oil: Decimal
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None = None
    created_by_name: str | None = None
    updated_by: uuid.UUID | None = None
    updated_by_name: str | None = None

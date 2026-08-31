import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class CommissionRateCreate(BaseModel):
    """All five figures are revised together as one OMC agreement change —
    see app/models/commission.py. Submitting the same effective_from again
    replaces that revision rather than erroring, matching the same pattern
    used for employee salary and lubricant price history.
    """

    effective_from: date
    petrol: Decimal = Field(gt=0, max_digits=10, decimal_places=3)
    diesel: Decimal = Field(gt=0, max_digits=10, decimal_places=3)
    oil: Decimal = Field(gt=0, max_digits=10, decimal_places=3)
    # Zero allowed (unlike the three fuel rates above) — a station that
    # doesn't sell packet/cane oil at all legitimately has no commission for
    # those categories, and the UI's fallback default before any rate has
    # ever been set is 0 for both.
    oil_packet: Decimal = Field(ge=0, max_digits=10, decimal_places=3)
    oil_cane: Decimal = Field(ge=0, max_digits=10, decimal_places=3)


class CommissionRateOut(ORMModel):
    id: uuid.UUID
    effective_from: date
    petrol: Decimal
    diesel: Decimal
    oil: Decimal
    oil_packet: Decimal
    oil_cane: Decimal
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None = None
    created_by_name: str | None = None
    updated_by: uuid.UUID | None = None
    updated_by_name: str | None = None

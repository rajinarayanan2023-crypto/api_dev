import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class SalaryPeriodCloseRequest(BaseModel):
    period_year: int = Field(ge=2000, le=2100)
    period_month: int = Field(ge=1, le=12)
    note: str | None = None


class SalaryPeriodActionRequest(BaseModel):
    """Body for the reopen action — same optional note, no period fields
    (those come from the path, since the period already exists by then).
    """

    note: str | None = None


class SalaryPeriodClosureOut(ORMModel):
    id: uuid.UUID
    period_year: int
    period_month: int
    status: str
    closed_at: datetime
    closed_by: uuid.UUID | None = None
    closed_by_name: str | None = None
    reopened_at: datetime | None = None
    reopened_by: uuid.UUID | None = None
    reopened_by_name: str | None = None
    note: str | None = None

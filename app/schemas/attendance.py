import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, model_validator

from app.models.attendance import AttendanceStatus
from app.schemas.common import ORMModel

_SHIFT_STATUSES = {AttendanceStatus.ONE_SHIFT, AttendanceStatus.DOUBLE_SHIFT}


class AttendanceBase(BaseModel):
    date: date
    status: AttendanceStatus
    start_time: time | None = None


# Only for user-submitted writes through this page's own API — a manager
# marking attendance by hand always has (or omits) a real start time. Not on
# AttendanceOut: reading an existing row back out and re-validating it as if
# it were a fresh submission is backwards — a row already on record is a true
# fact about the database regardless of this rule, and a GET must never 500
# just because this rule didn't exist (or looked different) when that row was
# originally written.
class _RequiresStartTimeForShifts:
    @model_validator(mode="after")
    def start_time_only_for_shifts(self):
        if self.status in _SHIFT_STATUSES and self.start_time is None:
            raise ValueError("start_time is required when status is one_shift or double_shift")
        if self.status not in _SHIFT_STATUSES and self.start_time is not None:
            raise ValueError("start_time must be omitted unless status is one_shift or double_shift")
        return self


class AttendanceCreate(AttendanceBase, _RequiresStartTimeForShifts):
    employee_id: uuid.UUID


class AttendanceUpdate(BaseModel, _RequiresStartTimeForShifts):
    status: AttendanceStatus
    start_time: time | None = None


class AttendanceOut(AttendanceBase, ORMModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None = None
    created_by_name: str | None = None
    updated_by: uuid.UUID | None = None
    updated_by_name: str | None = None

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
# AttendanceOut: reading back a row re-validating it as if it were a fresh
# submission is backwards — a row written by a different path entirely (Fuel
# Entry's auto-mark cascade goes straight through the repository, and has no
# start_time concept at all) is still a true fact about the database, and a
# GET must never 500 over how some other path chose to write it.
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

import enum
import uuid
from datetime import date, time

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Text, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuditMixin, Base, UUIDPkMixin


class AttendanceStatus(str, enum.Enum):
    ONE_SHIFT = "one_shift"
    DOUBLE_SHIFT = "double_shift"
    ABSENT = "absent"
    LEAVE = "leave"
    DUTY_OFF = "duty_off"
    # A company-declared off day (holiday/closure) — unlike DUTY_OFF, this
    # one counts as a paid day worked (see shiftUnits in ui/src/utils/
    # attendance.js) and is never treated as an absence/leave (see
    # FuelEntryForm's unavailableEmployeeIds), so the employee still shows as
    # assignable to a shift on it.
    COMPANY_OFF = "company_off"


class AttendanceRecord(Base, UUIDPkMixin, AuditMixin):
    __tablename__ = "Attendance_Records"
    __table_args__ = (
        UniqueConstraint("employee_id", "date", name="uq_attendance_records_employee_date"),
        CheckConstraint(
            "status IN ('one_shift', 'double_shift', 'absent', 'leave', 'duty_off', 'company_off')",
            name="ck_attendance_records_status",
        ),
        Index("idx_attendance_employee_date", "employee_id", "date"),
        # Serves list_for_range's whole-roster month view (no employee_id
        # filter) — the composite above leads with employee_id so it can't
        # help there (see migration d4a7e2c9f1b3).
        Index("idx_attendance_date", "date"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Employees.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    start_time: Mapped[time | None] = mapped_column(Time)

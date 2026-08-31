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


class AttendanceRecord(Base, UUIDPkMixin, AuditMixin):
    __tablename__ = "Attendance_Records"
    __table_args__ = (
        UniqueConstraint("employee_id", "date", name="uq_attendance_records_employee_date"),
        CheckConstraint(
            "status IN ('one_shift', 'double_shift', 'absent', 'leave', 'duty_off')",
            name="ck_attendance_records_status",
        ),
        Index("idx_attendance_employee_date", "employee_id", "date"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Employees.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    start_time: Mapped[time | None] = mapped_column(Time)

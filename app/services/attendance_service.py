import uuid
from datetime import date, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.models.attendance import AttendanceRecord
from app.models.user import User
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.employee_repository import EmployeeRepository
from app.schemas.attendance import AttendanceCreate, AttendanceUpdate
from app.services.audit import attach_actor_names
from app.services.salary_period_closure_service import SalaryPeriodClosureService


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, end - timedelta(days=1)


class AttendanceService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.attendance = AttendanceRepository(session)
        self.employees = EmployeeRepository(session)
        self.period_closures = SalaryPeriodClosureService(session)

    async def _ensure_employee_exists(self, employee_id: uuid.UUID) -> None:
        if await self.employees.get(employee_id) is None:
            raise NotFoundError("Employee not found.")

    async def mark_attendance(self, data: AttendanceCreate, actor: User) -> AttendanceRecord:
        employee = await self.employees.get(data.employee_id)
        if employee is None:
            raise NotFoundError("Employee not found.")
        # The UI's own "not yet joined" guard (hasNotJoinedYet in
        # Attendance.jsx) only ever disabled the Edit button — nothing
        # stopped a direct API call (or a future UI bug) from recording
        # attendance, and the payroll it feeds, for a day before the
        # employee existed or that hasn't happened yet.
        if data.date > date.today():
            raise AppError("Attendance date cannot be in the future.")
        if data.date < employee.join_date:
            raise AppError(
                f"This employee joined on {employee.join_date.isoformat()} — attendance can't be marked before that."
            )
        await self.period_closures.ensure_period_open(data.date.year, data.date.month)
        existing = await self.attendance.get_by_employee_and_date(data.employee_id, data.date)
        if existing is not None:
            raise ConflictError("Attendance for this employee and date is already recorded.")

        record = AttendanceRecord(
            employee_id=data.employee_id,
            date=data.date,
            status=data.status.value,
            start_time=data.start_time,
            created_by=actor.id,
            updated_by=actor.id,
        )
        try:
            created = await self.attendance.create(record)
        except IntegrityError as exc:
            # Two "mark attendance" requests racing for the same employee+day
            # both pass the "existing is None" check above before either has
            # saved — the table's own unique constraint catches the second
            # one; without this, that surfaced as a raw 500 instead of the
            # same clean message the non-racing case already gets above.
            if "uq_attendance_records_employee_date" in str(exc):
                raise ConflictError("Attendance for this employee and date is already recorded.") from exc
            raise
        await attach_actor_names(self.session, [created])
        return created

    async def update_attendance(
        self, employee_id: uuid.UUID, day: date, data: AttendanceUpdate, actor: User
    ) -> AttendanceRecord:
        record = await self.attendance.get_by_employee_and_date(employee_id, day)
        if record is None:
            raise NotFoundError("No attendance record found for this employee and date.")
        await self.period_closures.ensure_period_open(day.year, day.month)
        record.status = data.status.value
        record.start_time = data.start_time
        record.updated_by = actor.id
        await self.session.flush()
        await self.session.refresh(record)
        await attach_actor_names(self.session, [record])
        return record

    async def delete_attendance(self, employee_id: uuid.UUID, day: date) -> None:
        record = await self.attendance.get_by_employee_and_date(employee_id, day)
        if record is None:
            raise NotFoundError("No attendance record found for this employee and date.")
        await self.period_closures.ensure_period_open(day.year, day.month)
        await self.attendance.delete(record)

    async def list_for_month(self, employee_id: uuid.UUID, year: int, month: int) -> list[AttendanceRecord]:
        await self._ensure_employee_exists(employee_id)
        start, end = _month_bounds(year, month)
        records = await self.attendance.list_for_employee_in_range(employee_id, start, end)
        await attach_actor_names(self.session, records)
        return records

    async def list_all_for_month(self, year: int, month: int) -> list[AttendanceRecord]:
        start, end = _month_bounds(year, month)
        records = await self.attendance.list_for_range(start, end)
        await attach_actor_names(self.session, records)
        return records

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance import AttendanceRecord
from app.repositories.base import BaseRepository


class AttendanceRepository(BaseRepository[AttendanceRecord]):
    def __init__(self, session: AsyncSession):
        super().__init__(AttendanceRecord, session)

    async def get_by_employee_and_date(self, employee_id: uuid.UUID, day: date) -> AttendanceRecord | None:
        result = await self.session.execute(
            select(AttendanceRecord).where(AttendanceRecord.employee_id == employee_id, AttendanceRecord.date == day)
        )
        return result.scalar_one_or_none()

    async def list_for_employee_in_range(
        self, employee_id: uuid.UUID, start: date, end: date
    ) -> list[AttendanceRecord]:
        result = await self.session.execute(
            select(AttendanceRecord)
            .where(
                AttendanceRecord.employee_id == employee_id,
                AttendanceRecord.date >= start,
                AttendanceRecord.date <= end,
            )
            .order_by(AttendanceRecord.date)
        )
        return list(result.scalars().all())

    # Every employee's attendance for one month in a single query — the
    # Attendance page's Mark/History views need the whole roster at once,
    # not one employee at a time.
    async def list_for_range(self, start: date, end: date) -> list[AttendanceRecord]:
        result = await self.session.execute(
            select(AttendanceRecord)
            .where(AttendanceRecord.date >= start, AttendanceRecord.date <= end)
            .order_by(AttendanceRecord.date)
        )
        return list(result.scalars().all())

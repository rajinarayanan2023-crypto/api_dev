import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.fuel_entry import FuelEntry
from app.repositories.base import BaseRepository

_WITH_DETAIL = (
    selectinload(FuelEntry.readings),
    selectinload(FuelEntry.oil_rows),
    selectinload(FuelEntry.payment_lines),
    selectinload(FuelEntry.bills),
)


class FuelEntryRepository(BaseRepository[FuelEntry]):
    def __init__(self, session: AsyncSession):
        super().__init__(FuelEntry, session)

    async def get_with_details(self, id: uuid.UUID) -> FuelEntry | None:
        result = await self.session.execute(select(FuelEntry).options(*_WITH_DETAIL).where(FuelEntry.id == id))
        return result.scalar_one_or_none()

    async def list_with_details(self, offset: int = 0, limit: int = 1000) -> list[FuelEntry]:
        result = await self.session.execute(
            select(FuelEntry).options(*_WITH_DETAIL).order_by(FuelEntry.date.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all())

    async def count_final_for_employee_on_date(self, employee_id: uuid.UUID, day: date) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(FuelEntry).where(
                FuelEntry.employee_id == employee_id,
                FuelEntry.date == day,
                FuelEntry.internal_only.is_(False),
                FuelEntry.status == "final",
            )
        )
        return result.scalar_one()

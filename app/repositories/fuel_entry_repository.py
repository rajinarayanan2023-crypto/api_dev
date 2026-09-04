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

    # Used by FuelEntryService.update: takes a row lock on this FuelEntry for
    # the rest of the transaction, so a second concurrent update() call for
    # the same id (e.g. a debounced autosave landing right as a manual save
    # is in flight) blocks until the first one commits, instead of both
    # racing to replace the same Fuel_Readings rows and one of them hitting
    # uq_fuel_readings_entry_type_nozzle. FOR UPDATE only applies to the
    # FuelEntry row itself here — that's enough to fully serialize the two
    # update() calls, so the second one's own reads/writes of the child rows
    # only start once the first has already finished with them.
    async def get_with_details_for_update(self, id: uuid.UUID) -> FuelEntry | None:
        result = await self.session.execute(
            select(FuelEntry).options(*_WITH_DETAIL).where(FuelEntry.id == id).with_for_update(of=FuelEntry)
        )
        return result.scalar_one_or_none()

    async def list_with_details(
        self,
        offset: int = 0,
        limit: int = 1000,
        pump_key: str | None = None,
        entry_date: date | None = None,
        before: date | None = None,
    ) -> list[FuelEntry]:
        query = select(FuelEntry).options(*_WITH_DETAIL)
        if pump_key is not None:
            query = query.where(FuelEntry.pump_key == pump_key)
        if entry_date is not None:
            query = query.where(FuelEntry.date == entry_date)
        if before is not None:
            query = query.where(FuelEntry.date < before)
        query = query.order_by(FuelEntry.date.desc()).offset(offset).limit(limit)
        result = await self.session.execute(query)
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

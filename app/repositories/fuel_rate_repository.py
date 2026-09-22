from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fuel_rate import FuelRateHistory
from app.repositories.base import BaseRepository


class FuelRateRepository(BaseRepository[FuelRateHistory]):
    def __init__(self, session: AsyncSession):
        super().__init__(FuelRateHistory, session)

    async def get_by_date(self, effective_from: date) -> FuelRateHistory | None:
        result = await self.session.execute(
            select(FuelRateHistory).where(FuelRateHistory.effective_from == effective_from)
        )
        return result.scalar_one_or_none()

    async def get_current(self, as_of: date) -> FuelRateHistory | None:
        """The rate in force on `as_of`: the revision with the latest
        effective_from on or before that date."""
        result = await self.session.execute(
            select(FuelRateHistory)
            .where(FuelRateHistory.effective_from <= as_of)
            .order_by(FuelRateHistory.effective_from.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_all(self, offset: int = 0, limit: int = 500) -> list[FuelRateHistory]:
        result = await self.session.execute(
            select(FuelRateHistory).order_by(FuelRateHistory.effective_from.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all())

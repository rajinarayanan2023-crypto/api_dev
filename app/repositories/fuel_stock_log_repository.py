from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fuel_stock_log import FuelStockLog
from app.repositories.base import BaseRepository


class FuelStockLogRepository(BaseRepository[FuelStockLog]):
    def __init__(self, session: AsyncSession):
        super().__init__(FuelStockLog, session)

    async def get_by_date(self, log_date: date, is_shift3: bool = False) -> FuelStockLog | None:
        result = await self.session.execute(
            select(FuelStockLog).where(FuelStockLog.log_date == log_date, FuelStockLog.is_shift3 == is_shift3)
        )
        return result.scalar_one_or_none()

    # Full history, up to two rows per day (main + Shift 3) — still a small
    # dataset, loaded in full by the frontend same as fuel entries/
    # commission rates, which then finds "the latest checkpoint before X"
    # itself (see AuditModal.jsx) rather than this needing its own dedicated
    # lookup endpoint.
    async def list_all(self, offset: int = 0, limit: int = 500) -> list[FuelStockLog]:
        result = await self.session.execute(
            select(FuelStockLog).order_by(FuelStockLog.log_date.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all())

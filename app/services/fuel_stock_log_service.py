import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.fuel_stock_log import FuelStockLog
from app.models.user import User
from app.repositories.fuel_stock_log_repository import FuelStockLogRepository
from app.schemas.fuel_stock_log import FuelStockLogCreate
from app.services.audit import attach_actor_names


class FuelStockLogService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.logs = FuelStockLogRepository(session)

    # Replaces the existing row instead of inserting a duplicate when
    # (log_date, is_shift3) matches one already on record (re-saving the
    # same checkpoint, e.g. after correcting a delivery figure) — same
    # upsert-by-date pattern as fuel/commission rate history.
    async def create_or_revise(self, data: FuelStockLogCreate, actor: User) -> FuelStockLog:
        existing = await self.logs.get_by_date(data.log_date, data.is_shift3)
        if existing is not None:
            existing.petrol_opening_stock = data.petrol_opening_stock
            existing.petrol_stock_received = data.petrol_stock_received
            existing.diesel_opening_stock = data.diesel_opening_stock
            existing.diesel_stock_received = data.diesel_stock_received
            existing.updated_by = actor.id
            await self.session.flush()
            revised = await self.logs.get(existing.id)
            await attach_actor_names(self.session, [revised])
            return revised

        log = FuelStockLog(
            log_date=data.log_date,
            is_shift3=data.is_shift3,
            petrol_opening_stock=data.petrol_opening_stock,
            petrol_stock_received=data.petrol_stock_received,
            diesel_opening_stock=data.diesel_opening_stock,
            diesel_stock_received=data.diesel_stock_received,
            created_by=actor.id,
            updated_by=actor.id,
        )
        created = await self.logs.create(log)
        await attach_actor_names(self.session, [created])
        return created

    async def list_all(self, offset: int = 0, limit: int = 500) -> list[FuelStockLog]:
        logs = await self.logs.list_all(offset=offset, limit=limit)
        await attach_actor_names(self.session, logs)
        return logs

    async def delete(self, log_id: uuid.UUID) -> None:
        log = await self.logs.get(log_id)
        if log is None:
            raise NotFoundError("Fuel stock log not found.")
        await self.logs.delete(log)

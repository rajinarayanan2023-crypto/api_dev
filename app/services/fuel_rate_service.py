import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.fuel_rate import FuelRateHistory
from app.models.user import User
from app.repositories.fuel_rate_repository import FuelRateRepository
from app.schemas.fuel_rate import FuelRateCreate
from app.services.audit import attach_actor_names


class FuelRateService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.rates = FuelRateRepository(session)

    # Replaces the existing row instead of inserting a duplicate when
    # effective_from matches one already on record (e.g. a same-day
    # correction to a mistyped rate) — the table has a unique constraint on
    # effective_from, so a plain insert would otherwise raise IntegrityError
    # for what the manager sees as an edit. Same pattern as commission rate /
    # employee salary / lubricant price history.
    async def create_or_revise(self, data: FuelRateCreate, actor: User) -> FuelRateHistory:
        existing = await self.rates.get_by_date(data.effective_from)
        if existing is not None:
            existing.petrol = data.petrol
            existing.diesel = data.diesel
            existing.oil = data.oil
            existing.updated_by = actor.id
            await self.session.flush()
            # updated_at is server-computed (onupdate=now()) — flush()
            # expires it (without reloading) rather than fetching the new
            # value, which would otherwise crash Pydantic serialization by
            # forcing a lazy-load outside an active await. A fresh fetch
            # sidesteps that entirely.
            revised = await self.rates.get(existing.id)
            await attach_actor_names(self.session, [revised])
            return revised

        rate = FuelRateHistory(
            effective_from=data.effective_from,
            petrol=data.petrol,
            diesel=data.diesel,
            oil=data.oil,
            created_by=actor.id,
            updated_by=actor.id,
        )
        created = await self.rates.create(rate)
        await attach_actor_names(self.session, [created])
        return created

    async def get_current(self, as_of: date | None = None) -> FuelRateHistory:
        rate = await self.rates.get_current(as_of or date.today())
        if rate is None:
            raise NotFoundError("No fuel rate has been set yet.")
        await attach_actor_names(self.session, [rate])
        return rate

    async def list_all(self, offset: int = 0, limit: int = 500) -> list[FuelRateHistory]:
        rates = await self.rates.list_all(offset=offset, limit=limit)
        await attach_actor_names(self.session, rates)
        return rates

    async def delete(self, rate_id: uuid.UUID) -> None:
        rate = await self.rates.get(rate_id)
        if rate is None:
            raise NotFoundError("Fuel rate revision not found.")
        await self.rates.delete(rate)

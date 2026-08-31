from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.commission import CommissionRateHistory
from app.models.user import User
from app.repositories.commission_repository import CommissionRateRepository
from app.schemas.commission import CommissionRateCreate
from app.services.audit import attach_actor_names


class CommissionRateService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.rates = CommissionRateRepository(session)

    # Replaces the existing row instead of inserting a duplicate when
    # effective_from matches one already on record (e.g. a same-day
    # correction) — the table has a unique constraint on effective_from, so a
    # plain insert would otherwise raise IntegrityError for what the manager
    # sees as an edit. Same pattern as employee salary / lubricant price history.
    async def create_or_revise(self, data: CommissionRateCreate, actor: User) -> CommissionRateHistory:
        existing = await self.rates.get_by_date(data.effective_from)
        if existing is not None:
            existing.petrol = data.petrol
            existing.diesel = data.diesel
            existing.oil = data.oil
            existing.oil_packet = data.oil_packet
            existing.oil_cane = data.oil_cane
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

        rate = CommissionRateHistory(
            effective_from=data.effective_from,
            petrol=data.petrol,
            diesel=data.diesel,
            oil=data.oil,
            oil_packet=data.oil_packet,
            oil_cane=data.oil_cane,
            created_by=actor.id,
            updated_by=actor.id,
        )
        created = await self.rates.create(rate)
        await attach_actor_names(self.session, [created])
        return created

    async def get_current(self, as_of: date | None = None) -> CommissionRateHistory:
        rate = await self.rates.get_current(as_of or date.today())
        if rate is None:
            raise NotFoundError("No commission rate has been set yet.")
        await attach_actor_names(self.session, [rate])
        return rate

    async def list_all(self, offset: int = 0, limit: int = 200) -> list[CommissionRateHistory]:
        rates = await self.rates.list_all(offset=offset, limit=limit)
        await attach_actor_names(self.session, rates)
        return rates

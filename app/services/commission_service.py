import uuid
from datetime import date, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import invalidate_dashboard_from_month
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.models.commission import CommissionRateHistory
from app.models.user import User
from app.repositories.commission_repository import CommissionRateRepository
from app.schemas.commission import CommissionRateCreate
from app.services.audit import attach_actor_names
from app.services.salary_period_closure_service import SalaryPeriodClosureService

# Sanity bounds, not business rules — these exist purely to catch fat-finger
# input (a wrong year, an extra digit on a rate) before it's saved and
# silently recalculates months of commission. A real "no such thing as a
# before-2015 fuel station record for this app, or a rate change scheduled
# literally years out" case should never actually hit these; a typo like
# "2524" instead of "2026", or "50000" instead of "5.00", should.
_EARLIEST_EFFECTIVE_FROM = date(2015, 1, 1)
_FURTHEST_FUTURE_EFFECTIVE_FROM_DAYS = 365 * 2
_MAX_SANE_RATE = 1000


def _validate_rate_sanity(data: CommissionRateCreate) -> None:
    today = date.today()
    furthest_future = today + timedelta(days=_FURTHEST_FUTURE_EFFECTIVE_FROM_DAYS)
    if not (_EARLIEST_EFFECTIVE_FROM <= data.effective_from <= furthest_future):
        raise AppError(
            f"Effective date {data.effective_from.isoformat()} looks wrong — it must be between "
            f"{_EARLIEST_EFFECTIVE_FROM.isoformat()} and {furthest_future.isoformat()}. "
            "Double-check the year."
        )
    for label, value in (
        ("Petrol", data.petrol),
        ("Diesel", data.diesel),
        ("2T Oil", data.oil),
        ("2T Packet", data.oil_packet),
        ("Servo Oil", data.oil_cane),
    ):
        if value > _MAX_SANE_RATE:
            raise AppError(f"{label} rate of ₹{value} looks wrong — commission rates this high aren't expected. Double-check the value.")


class CommissionRateService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.rates = CommissionRateRepository(session)
        self.period_closures = SalaryPeriodClosureService(session)

    # Replaces the existing row instead of inserting a duplicate when
    # effective_from matches one already on record (e.g. a same-day
    # correction) — the table has a unique constraint on effective_from, so a
    # plain insert would otherwise raise IntegrityError for what the manager
    # sees as an edit. Same pattern as employee salary / lubricant price history.
    async def create_or_revise(self, data: CommissionRateCreate, actor: User) -> CommissionRateHistory:
        _validate_rate_sanity(data)
        # A revision is in force until superseded, so it can retroactively
        # change what applies for every LATER month too, not just its own —
        # same ripple-forward reasoning as salary revisions (see
        # SalaryPeriodClosureService.ensure_no_closed_period_on_or_after).
        # Blast radius is at least as wide as a salary revision's, so it gets
        # the same guard.
        await self.period_closures.ensure_no_closed_period_on_or_after(
            data.effective_from.year, data.effective_from.month
        )
        existing = await self.rates.get_by_date(data.effective_from)
        if existing is not None:
            existing.petrol = data.petrol
            existing.diesel = data.diesel
            existing.oil = data.oil
            existing.oil_packet = data.oil_packet
            existing.oil_cane = data.oil_cane
            existing.updated_by = actor.id
            await self.session.flush()
            # Invalidated only now that the write has actually happened —
            # doing this beforehand (as this used to) let a concurrent read
            # land in the gap and re-cache the pre-update figures for the
            # rest of the TTL window.
            invalidate_dashboard_from_month(data.effective_from.strftime("%Y-%m"))
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
        try:
            created = await self.rates.create(rate)
        except IntegrityError as exc:
            # Two requests racing to save the same brand-new effective_from
            # both pass the "does this exist" check above before either has
            # saved — the table's own unique constraint catches the second
            # one; without this, that surfaced as a raw 500 instead of a
            # clean conflict message. Same pattern as expense/fuel-entry
            # services' own unique-date races.
            if "Commission_Rate_History_effective_from_key" in str(exc):
                raise ConflictError(
                    "Another revision for this exact date was just saved — refresh and try again."
                ) from exc
            raise
        invalidate_dashboard_from_month(data.effective_from.strftime("%Y-%m"))
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

    async def delete(self, rate_id: uuid.UUID) -> None:
        rate = await self.rates.get(rate_id)
        if rate is None:
            raise NotFoundError("Commission rate revision not found.")
        # Same ripple-forward reasoning as create_or_revise: removing a
        # revision changes the applicable rate for its own month AND every
        # later one (until whatever rate comes next now applies instead).
        await self.period_closures.ensure_no_closed_period_on_or_after(
            rate.effective_from.year, rate.effective_from.month
        )
        await self.rates.delete(rate)
        # Invalidated only now that the delete has actually happened.
        invalidate_dashboard_from_month(rate.effective_from.strftime("%Y-%m"))

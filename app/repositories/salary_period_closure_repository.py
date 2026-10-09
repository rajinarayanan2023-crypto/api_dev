from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import SalaryPeriodClosure
from app.repositories.base import BaseRepository


class SalaryPeriodClosureRepository(BaseRepository[SalaryPeriodClosure]):
    def __init__(self, session: AsyncSession):
        super().__init__(SalaryPeriodClosure, session)

    async def get_by_period(self, period_year: int, period_month: int) -> SalaryPeriodClosure | None:
        result = await self.session.execute(
            select(SalaryPeriodClosure).where(
                SalaryPeriodClosure.period_year == period_year,
                SalaryPeriodClosure.period_month == period_month,
            )
        )
        return result.scalar_one_or_none()

    # Acquires a row lock on this period's closure row for the rest of the
    # current transaction, if it already exists — closes the race where two
    # concurrent close (or reopen) requests on an already-existing row (one
    # closed/reopened before, then reused — see SalaryPeriodClosure's own
    # docstring) both read the same starting status before either has saved,
    # silently losing one's close/reopen to the other instead of the second
    # one getting a clean 409. A brand-new period (no row yet) has nothing to
    # lock — that race is already closed by the table's own unique
    # constraint, caught as an IntegrityError in close_period. Same pattern
    # as LubricantRepository.lock_for_update /
    # CreditCustomerRepository.lock_for_update.
    async def lock_for_update(self, period_year: int, period_month: int) -> None:
        await self.session.execute(
            select(SalaryPeriodClosure.id)
            .where(
                SalaryPeriodClosure.period_year == period_year,
                SalaryPeriodClosure.period_month == period_month,
            )
            .with_for_update()
        )

    # Small table (a handful of rows per year, at most) — loaded in full so
    # callers can both render every period's status and, for the "could this
    # salary revision ripple into a closed month" guard, compare against
    # every closed period at once rather than needing a dedicated range query.
    async def list_all(self) -> list[SalaryPeriodClosure]:
        result = await self.session.execute(
            select(SalaryPeriodClosure).order_by(
                SalaryPeriodClosure.period_year.desc(), SalaryPeriodClosure.period_month.desc()
            )
        )
        return list(result.scalars().all())

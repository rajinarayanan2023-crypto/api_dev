import logging
from calendar import monthrange
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import dashboard_cache, dashboard_cache_key
from app.models.commission import CommissionRateHistory
from app.repositories.commission_repository import CommissionRateRepository
from app.repositories.expense_repository import ExpenseDayRepository
from app.repositories.fuel_entry_repository import FuelEntryRepository

logger = logging.getLogger("app.dashboard")

_ZERO = Decimal("0")


def _month_bounds(month: str) -> tuple[date, date]:
    year, mon = (int(part) for part in month.split("-"))
    start = date(year, mon, 1)
    end = date(year, mon, monthrange(year, mon)[1])
    return start, end


# Same "latest liters" rule FuelEntryService._reading_liters uses elsewhere —
# duplicated here rather than imported to keep this module's only dependency
# on fuel_entry internals the ORM models themselves (readings/oil_rows),
# not another service's private helper.
def _reading_liters(opening: Decimal, closing: Decimal, testing: Decimal) -> Decimal:
    return max(_ZERO, (closing or _ZERO) - (opening or _ZERO) - (testing or _ZERO))


# Mirrors CommissionRateRepository.get_current's "latest effective_from <=
# date" rule, but resolved in memory against one pre-fetched, ascending list
# — the whole point of fetching the history once per month instead of
# running a get_current-style query per fuel entry (N+1 avoided for a month
# with dozens of entries). `rates` must already be sorted ascending by
# effective_from (see CommissionRateRepository.list_all_ascending).
def _rate_for_date(rates: list[CommissionRateHistory], entry_date: date) -> CommissionRateHistory | None:
    applicable = None
    for rate in rates:
        if rate.effective_from <= entry_date:
            applicable = rate
        else:
            break
    return applicable  # None => entry predates every rate on record (or none exist yet)


class DashboardService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.entries = FuelEntryRepository(session)
        self.expenses = ExpenseDayRepository(session)
        self.rates = CommissionRateRepository(session)

    async def get_summary(self, month: str) -> dict:
        cache_key = dashboard_cache_key(month)
        cached = dashboard_cache.get(cache_key)
        if cached is not None:
            logger.info("dashboard summary cache hit for %s", month)
            return cached

        logger.info("dashboard summary cache miss for %s — computing", month)
        start, end = _month_bounds(month)
        entries = await self.entries.list_final_in_range(start, end)
        expense_days = await self.expenses.list_with_items_in_range(start, end)
        rates = await self.rates.list_all_ascending()

        petrol_litres = diesel_litres = oil_machine_litres = _ZERO
        oil_packet_units = oil_packet_amount = _ZERO
        oil_cane_units = oil_cane_amount = _ZERO
        commission_earned = _ZERO

        for entry in entries:
            fuel_litres = {"petrol": _ZERO, "diesel": _ZERO, "oil": _ZERO}
            for reading in entry.readings:
                fuel_litres[reading.fuel_type] += _reading_liters(reading.opening, reading.closing, reading.testing)
            petrol_litres += fuel_litres["petrol"]
            diesel_litres += fuel_litres["diesel"]
            oil_machine_litres += fuel_litres["oil"]

            entry_packet_qty = entry_cane_qty = _ZERO
            for row in entry.oil_rows:
                qty = row.stock_count or _ZERO
                amount = qty * (row.stock_rate or _ZERO)
                if row.row_type == "pocket":
                    entry_packet_qty += qty
                    oil_packet_amount += amount
                else:
                    entry_cane_qty += qty
                    oil_cane_amount += amount
            oil_packet_units += entry_packet_qty
            oil_cane_units += entry_cane_qty

            rate = _rate_for_date(rates, entry.date)
            if rate is not None:
                commission_earned += (
                    fuel_litres["petrol"] * rate.petrol
                    + fuel_litres["diesel"] * rate.diesel
                    + fuel_litres["oil"] * rate.oil
                    + entry_packet_qty * rate.oil_packet
                    + entry_cane_qty * rate.oil_cane
                )
            # else: this entry's date predates every rate on record (or the
            # table is empty) — contributes 0 commission, not an error; the
            # litres/expenses/profit figures still reflect real data.

        total_expenses = sum((item.amount for day in expense_days for item in day.items), _ZERO)
        profit = commission_earned - total_expenses

        summary = {
            "petrol_litres": petrol_litres,
            "diesel_litres": diesel_litres,
            "oil_machine_litres": oil_machine_litres,
            "oil_packet_units": oil_packet_units,
            "oil_packet_amount": oil_packet_amount,
            "oil_cane_units": oil_cane_units,
            "oil_cane_amount": oil_cane_amount,
            "commission_earned": commission_earned,
            "total_expenses": total_expenses,
            "profit": profit,
            "rate_status": "no_rates_configured" if not rates else "using_historical_rates",
        }
        dashboard_cache.set(cache_key, summary)
        return summary

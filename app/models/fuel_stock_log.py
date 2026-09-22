from datetime import date

from sqlalchemy import Boolean, Date, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuditMixin, Base, UUIDPkMixin


class FuelStockLog(Base, UUIDPkMixin, AuditMixin):
    """One checkpoint in the tank's running stock timeline — the two figures
    a manager can't get from anywhere else in the system: how much petrol/
    diesel was already in the tank before this checkpoint's own delivery
    (Opening Stock), and how much was delivered during it (Stock Received).
    Everything else the Audit report's "Fuel Stock" table needs (Sold,
    Current Stock) is computed live from the real fuel entries and these two
    figures — never stored here — so it can never go stale if a meter
    reading is corrected after the fact.

    Up to TWO checkpoints per calendar date, distinguished by is_shift3: the
    main day audit (shift 1+2, is_shift3=False) and, only on a day the OMC
    changed price, a second one for Shift 3's own separate reading
    (is_shift3=True). Shift 3's Opening Stock always carries from that SAME
    date's main-day checkpoint (never a previous date's) — it's a
    continuation within the same day, not a new day. The next CALENDAR DAY's
    main audit then carries from whichever checkpoint is chronologically
    latest for the most recent earlier date: that date's Shift 3 checkpoint
    if it has one, otherwise its main-day one.

    Unique on (log_date, is_shift3): saving the same checkpoint again (a
    same-day correction) replaces that row instead of erroring, same
    upsert-by-date pattern as Fuel_Rate_History/Commission_Rate_History.
    """

    __tablename__ = "Fuel_Stock_Log"
    __table_args__ = (UniqueConstraint("log_date", "is_shift3", name="uq_fuel_stock_log_date_shift3"),)

    log_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_shift3: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    petrol_opening_stock: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    petrol_stock_received: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False, default=0)
    diesel_opening_stock: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    diesel_stock_received: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False, default=0)

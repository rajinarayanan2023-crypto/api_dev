from datetime import date

from sqlalchemy import Date, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuditMixin, Base, UUIDPkMixin


class FuelRateHistory(Base, UUIDPkMixin, AuditMixin):
    """Retail selling rate for petrol/diesel/2T oil, versioned by the date it
    took effect — same date-effective pattern as Commission_Rate_History,
    employee salary, and lubricant price history: the entry whose
    effective_from is the latest one on/before a given date is the rate in
    force on that date. Previously tracked only in the browser (localStorage)
    with 2T oil hardcoded to a fixed constant everywhere else in the app —
    this table is the real, shared source of truth so a rate revision is
    visible from any device and survives clearing browser storage, and 2T oil
    can now be revised over time same as petrol/diesel instead of staying fixed.
    """

    __tablename__ = "Fuel_Rate_History"

    effective_from: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
    petrol: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    diesel: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    oil: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

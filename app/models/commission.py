from datetime import date

from sqlalchemy import Date, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuditMixin, Base, UUIDPkMixin


class CommissionRateHistory(Base, UUIDPkMixin, AuditMixin):
    """All five figures (three per-litre, two per-piece) are revised together
    as one OMC agreement change, so they're versioned as a single dated
    snapshot rather than five separate per-fuel history tables — the entry
    whose effective_from is the latest one on/before a given date is the rate
    in force on that date.
    """

    __tablename__ = "Commission_Rate_History"

    effective_from: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
    petrol: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    diesel: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    oil: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    oil_packet: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    oil_cane: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)

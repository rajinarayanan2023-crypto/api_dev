import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditMixin, Base, UUIDPkMixin


class FuelEntry(Base, UUIDPkMixin, AuditMixin):
    """One row = one employee, one pump, one shift, one day."""

    __tablename__ = "Fuel_Entries"
    __table_args__ = (
        UniqueConstraint("date", "pump_key", "shift_number", name="uq_fuel_entries_date_pump_shift"),
        CheckConstraint("pump_key IN ('pump1', 'pump2')", name="ck_fuel_entries_pump_key"),
        CheckConstraint("shift_number IN (1, 2, 3)", name="ck_fuel_entries_shift_number"),
        CheckConstraint("status IN ('draft', 'final')", name="ck_fuel_entries_status"),
        Index("idx_fuel_entries_date", "date"),
        Index("idx_fuel_entries_pump_date", "pump_key", "date"),
        Index("idx_fuel_entries_employee", "employee_id"),
        # Matches count_final_for_employee_on_date's exact filter (the
        # attendance auto-mark cascade, run on every finalized fuel entry) —
        # migration d4a7e2c9f1b3. idx_fuel_entries_employee above is now
        # largely superseded by this via the leftmost-prefix rule but is
        # left in place; this migration only adds what was missing.
        Index("idx_fuel_entries_employee_date", "employee_id", "date"),
    )

    date: Mapped[date] = mapped_column(Date, nullable=False)
    pump_key: Mapped[str] = mapped_column(Text, nullable=False)
    shift_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # true only for shift 3; excluded from attendance auto-marking
    internal_only: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Employees.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    cane_oil_offer: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, server_default=text("0"))
    notes: Mapped[str | None] = mapped_column(Text)

    readings: Mapped[list["FuelReading"]] = relationship(back_populates="fuel_entry", cascade="all, delete-orphan")
    oil_rows: Mapped[list["FuelEntryOilRow"]] = relationship(
        back_populates="fuel_entry", cascade="all, delete-orphan"
    )
    payment_lines: Mapped[list["PaymentLine"]] = relationship(
        back_populates="fuel_entry", cascade="all, delete-orphan"
    )
    bills: Mapped[list["FuelEntryBill"]] = relationship(back_populates="fuel_entry", cascade="all, delete-orphan")


class FuelReading(Base, UUIDPkMixin):
    """Up to 6 rows per entry: {petrol,diesel,oil} x {nozzle1,nozzle2}. oil
    only applies to pump2 — enforced in application code, not a DB constraint.
    """

    __tablename__ = "Fuel_Readings"
    __table_args__ = (
        UniqueConstraint("fuel_entry_id", "fuel_type", "nozzle", name="uq_fuel_readings_entry_type_nozzle"),
        CheckConstraint("fuel_type IN ('petrol', 'diesel', 'oil')", name="ck_fuel_readings_fuel_type"),
        CheckConstraint("nozzle IN ('nozzle1', 'nozzle2')", name="ck_fuel_readings_nozzle"),
        Index("idx_fuel_readings_entry", "fuel_entry_id"),
    )

    fuel_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Fuel_Entries.id", ondelete="CASCADE"), nullable=False
    )
    fuel_type: Mapped[str] = mapped_column(Text, nullable=False)
    nozzle: Mapped[str] = mapped_column(Text, nullable=False)
    opening: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, server_default=text("0"))
    closing: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, server_default=text("0"))
    testing: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False, server_default=text("0"))
    rate: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False, server_default=text("0"))

    fuel_entry: Mapped["FuelEntry"] = relationship(back_populates="readings")


class FuelEntryOilRow(Base, UUIDPkMixin):
    """Pump 2 only — sachet/can oil sold by count, not through a nozzle."""

    __tablename__ = "Fuel_Entry_Oil_Rows"
    __table_args__ = (
        CheckConstraint("row_type IN ('pocket', 'cane')", name="ck_fuel_entry_oil_rows_row_type"),
        Index("idx_fuel_entry_oil_rows_entry", "fuel_entry_id"),
        Index("idx_fuel_entry_oil_rows_product", "product_id"),
    )

    fuel_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Fuel_Entries.id", ondelete="CASCADE"), nullable=False
    )
    row_type: Mapped[str] = mapped_column(Text, nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Lubricant_Products.id", ondelete="SET NULL")
    )
    # Numeric, not Integer — a count can be fractional (e.g. a partial cane
    # tin), and the UI clamps against a stock figure already rounded to 3
    # decimals (migration e2b7c4f9a1d6).
    stock_count: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False, server_default=text("0"))
    stock_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, server_default=text("0"))

    fuel_entry: Mapped["FuelEntry"] = relationship(back_populates="oil_rows")


class PaymentLine(Base, UUIDPkMixin):
    """How the shift's takings were collected: cash, card, QR, a customer
    credit, or an advance against an employee's pay.
    """

    __tablename__ = "Payment_Lines"
    __table_args__ = (
        # 'expense' allowed since migration 8f3c1a9d5e2b — this declaration
        # had drifted out of sync with the live constraint until now.
        CheckConstraint("type IN ('cash', 'credit', 'employee_credit', 'expense')", name="ck_payment_lines_type"),
        Index("idx_payment_lines_entry", "fuel_entry_id"),
        Index("idx_payment_lines_customer", "customer_id"),
        Index("idx_payment_lines_employee", "employee_id"),
    )

    fuel_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Fuel_Entries.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default=text("0"))
    type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'cash'"))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Credit_Customers.id", ondelete="SET NULL")
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Employees.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)
    # Till-count breakdown for a cash line — {"500": n, "200": n, ..., "coins": n}
    # — opaque to the backend, kept only so the manager's actual note count
    # survives a save; `amount` (derived client-side) stays authoritative.
    denominations: Mapped[dict | None] = mapped_column(JSONB)

    fuel_entry: Mapped["FuelEntry"] = relationship(back_populates="payment_lines")


class FuelEntryBill(Base, UUIDPkMixin):
    """Photo/scan attachments — at least one required before an entry can go
    final (enforced in application code).
    """

    __tablename__ = "Fuel_Entry_Bills"
    __table_args__ = (Index("idx_fuel_entry_bills_entry", "fuel_entry_id"),)

    fuel_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Fuel_Entries.id", ondelete="CASCADE"), nullable=False
    )
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=text("CURRENT_DATE"))

    fuel_entry: Mapped["FuelEntry"] = relationship(back_populates="bills")

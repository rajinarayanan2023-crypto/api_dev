import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditMixin, Base, UUIDPkMixin


class CreditCustomer(Base, UUIDPkMixin, AuditMixin):
    __tablename__ = "Credit_Customers"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str | None] = mapped_column(Text)
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default=text("0"))
    notes: Mapped[str | None] = mapped_column(Text)

    ledger_entries: Mapped[list["CreditLedgerEntry"]] = relationship(
        back_populates="customer", cascade="all, delete-orphan", order_by="CreditLedgerEntry.date"
    )
    bills: Mapped[list["CreditCustomerBill"]] = relationship(back_populates="customer", cascade="all, delete-orphan")


class CreditCustomerBill(Base, UUIDPkMixin):
    """Not part of the supplied schema — mirrors Fuel_Entry_Bills, but for
    documents uploaded straight onto a customer's record (the "Bills &
    Documents" section) rather than tied to one ledger entry.
    """

    __tablename__ = "Credit_Customer_Bills"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Credit_Customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=text("CURRENT_DATE"))

    customer: Mapped["CreditCustomer"] = relationship(back_populates="bills")


class CreditLedgerEntry(Base, UUIDPkMixin):
    """Closing balance for a customer = opening_balance + SUM(credit) - SUM(payment)."""

    __tablename__ = "Credit_Ledger_Entries"
    __table_args__ = (
        CheckConstraint("type IN ('credit', 'payment')", name="ck_credit_ledger_entries_type"),
        CheckConstraint(
            "fuel_type IS NULL OR fuel_type IN ('petrol', 'diesel', 'oil')",
            name="ck_credit_ledger_entries_fuel_type",
        ),
        Index("idx_credit_ledger_entries_customer", "customer_id", "date"),
        # FK, filtered directly in FuelEntryService._remove_credit_ledger_by_source
        # on every edit/delete of an already-final fuel entry (migration d4a7e2c9f1b3).
        Index("idx_credit_ledger_entries_source_fuel_entry", "source_fuel_entry_id"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Credit_Customers.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    fuel_type: Mapped[str | None] = mapped_column(Text)  # set for a credit row
    litres: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))  # set for a credit row
    rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))  # set for a credit row
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    mode: Mapped[str | None] = mapped_column(Text)  # set for a payment row
    note: Mapped[str | None] = mapped_column(Text)
    source_fuel_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Fuel_Entries.id", ondelete="SET NULL")
    )
    # Not part of the supplied schema — a single optional bill attached
    # directly to one credit row (recorded when the credit sale is entered),
    # distinct from the general per-customer documents in Credit_Customer_Bills.
    bill_file_name: Mapped[str | None] = mapped_column(Text)
    bill_file_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    customer: Mapped["CreditCustomer"] = relationship(back_populates="ledger_entries")

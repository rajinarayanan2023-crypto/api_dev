import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Index, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditMixin, Base, UUIDPkMixin


class ExpenseDay(Base, UUIDPkMixin, AuditMixin):
    __tablename__ = "Expense_Days"

    date: Mapped[date] = mapped_column(Date, unique=True, nullable=False)

    items: Mapped[list["ExpenseItem"]] = relationship(back_populates="expense_day", cascade="all, delete-orphan")


class ExpenseItem(Base, UUIDPkMixin):
    __tablename__ = "Expense_Items"
    __table_args__ = (Index("idx_expense_items_day", "expense_day_id"),)

    expense_day_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Expense_Days.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)  # free-typed: "Tea", "Cleaning", "Delivery boy"
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    expense_day: Mapped["ExpenseDay"] = relationship(back_populates="items")

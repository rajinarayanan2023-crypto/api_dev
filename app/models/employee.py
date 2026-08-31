import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Numeric, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditMixin, Base, UUIDPkMixin


class Employee(Base, UUIDPkMixin, AuditMixin):
    __tablename__ = "Employees"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    father_name: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    join_date: Mapped[date] = mapped_column(Date, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    notes: Mapped[str | None] = mapped_column(Text)

    salary_history: Mapped[list["EmployeeSalaryHistory"]] = relationship(
        back_populates="employee", cascade="all, delete-orphan", order_by="EmployeeSalaryHistory.effective_from"
    )
    credits: Mapped[list["EmployeeCredit"]] = relationship(back_populates="employee", cascade="all, delete-orphan")


class EmployeeSalaryHistory(Base, UUIDPkMixin):
    """Pay in force on any date = latest row with effective_from <= that date."""

    __tablename__ = "Employee_Salary_History"
    __table_args__ = (
        UniqueConstraint("employee_id", "effective_from", name="uq_employee_salary_history"),
        Index("idx_salary_history_employee", "employee_id", "effective_from"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Employees.id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)

    employee: Mapped["Employee"] = relationship(back_populates="salary_history")


class EmployeeCredit(Base, UUIDPkMixin):
    """Advance taken by an employee at the pump, owed back against future pay."""

    __tablename__ = "Employee_Credits"
    __table_args__ = (Index("idx_employee_credits_employee", "employee_id", "date"),)

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Employees.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    source_fuel_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Fuel_Entries.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    employee: Mapped["Employee"] = relationship(back_populates="credits")

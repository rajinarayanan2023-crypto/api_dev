import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditMixin, Base, UUIDPkMixin


class Employee(Base, UUIDPkMixin, AuditMixin):
    __tablename__ = "Employees"
    __table_args__ = (
        # Backs EmployeeRepository.get_by_name_and_father_name's own
        # case/whitespace-insensitive, NULL-as-empty duplicate check with a
        # real database rule — without this, two "create employee" requests
        # racing at the same instant could both pass that check and both
        # succeed, silently creating two records for the same person with no
        # error at all (unlike a plain UniqueConstraint, a functional index
        # is required here since the duplicate rule itself is
        # case-insensitive and treats a missing father_name as equivalent to
        # an empty one).
        Index(
            "uq_employees_name_father_name_ci",
            text("lower(name)"),
            text("lower(coalesce(father_name, ''))"),
            unique=True,
        ),
    )

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
    payments: Mapped[list["SalaryPayment"]] = relationship(
        back_populates="employee", cascade="all, delete-orphan", order_by="SalaryPayment.paid_date"
    )


class EmployeeSalaryHistory(Base, UUIDPkMixin, AuditMixin):
    """Pay in force on any date = latest row with effective_from <= that date.

    Gained AuditMixin (migration pending as of this commit) for the same
    reason EmployeeCredit did (see its own docstring): a salary change is at
    least as sensitive as a credit entry, and until now nothing recorded who
    changed an employee's pay or when.
    """

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


class EmployeeCredit(Base, UUIDPkMixin, AuditMixin):
    """Advance taken by an employee at the pump, owed back against future pay.

    Originally a child/detail table left without its own audit trail (see
    migration 70a270f302c0) since it only ever existed as a side effect of
    Fuel Entry. Now also directly created/edited/deleted from its own
    standalone screen, so — unlike other child tables — it gets full
    created_at/updated_at/created_by/updated_by via AuditMixin (migration
    f3e7a9c1b5d8).
    """

    __tablename__ = "Employee_Credits"
    __table_args__ = (
        CheckConstraint("type IN ('credit', 'repayment', 'excess')", name="ck_employee_credits_type"),
        Index("idx_employee_credits_employee", "employee_id", "date"),
        # FK, filtered directly in FuelEntryService._remove_employee_credit_by_source
        # on every edit/delete of an already-final fuel entry (migration d4a7e2c9f1b3).
        Index("idx_employee_credits_source_fuel_entry", "source_fuel_entry_id"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Employees.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    # 'credit' = money advanced to the employee (owed back), e.g. a manual
    # advance OR a Fuel Entry shift's cash SHORTAGE (see
    # FuelEntryService._apply_shift_variance_credit). 'repayment' = the
    # employee handing cash back directly, separate from it just being
    # deducted from pay. 'excess' = the pump owing the employee back, e.g. a
    # Fuel Entry shift's cash EXCESS, or a manual correction for the same
    # reason — added to pay, same arithmetic direction as 'repayment' but a
    # distinct real-world event (never an actual repayment of a debt), so it
    # gets its own type rather than being silently folded into 'repayment'.
    # Always stored as a positive amount either way — the sign is implied by
    # type, never typed in by a manager, so the monthly total (credits minus
    # repayments minus excess) never depends on anyone remembering to enter a
    # negative number.
    type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'credit'"))
    note: Mapped[str | None] = mapped_column(Text)
    source_fuel_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Fuel_Entries.id", ondelete="SET NULL")
    )

    employee: Mapped["Employee"] = relationship(back_populates="credits")


class SalaryPayment(Base, UUIDPkMixin, AuditMixin):
    """An actual salary payout to an employee — distinct from EmployeeCredit
    (money advanced to the employee, owed back) and from the computed
    "payable" figure Salary.jsx derives live from salary_history/attendance/
    credits (utils/salary.js — never stored anywhere). This table is the
    first and only place an actual disbursement is ever recorded; before it
    existed, there was no record of what had genuinely been paid out, only
    a live recalculation of what was currently owed.

    `payable_snapshot` freezes what the live "payable" figure showed at the
    moment this payment was recorded — deliberately never recomputed or
    updated afterward, even if attendance/credits for that period are edited
    later. Without this, editing a past month's attendance would silently
    rewrite what a payment "should have" covered, with no way to tell
    whether a historical payment was fair when it was actually made. It's
    informational only, never read back to influence any calculation.

    No UniqueConstraint on (employee_id, period_year, period_month) —
    unlike salary history's one-rate-per-date rule, a manager may genuinely
    split one period's salary into more than one payment (a partial advance
    payout now, the remainder later), same reasoning as EmployeeCredit
    allowing more than one advance on the same date.
    """

    __tablename__ = "Salary_Payments"
    __table_args__ = (
        CheckConstraint("period_month BETWEEN 1 AND 12", name="ck_salary_payments_period_month"),
        Index("idx_salary_payments_employee_period", "employee_id", "period_year", "period_month"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Employees.id", ondelete="CASCADE"), nullable=False
    )
    # Which month this payment is FOR — never inferred from paid_date, since
    # a payment is often made days (or weeks) into the following month.
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    payable_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    paid_date: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    employee: Mapped["Employee"] = relationship(back_populates="payments")


class SalaryPeriodClosure(Base, UUIDPkMixin, AuditMixin):
    """A payroll month locked against further salary-affecting changes.

    One row per (period_year, period_month) EVER closed, reused across every
    close/reopen cycle (never deleted) so the full history survives: closing
    again after a reopen overwrites closed_at/closed_by but reopened_at/
    reopened_by from the earlier reopen stay in place, and vice versa — both
    sides of the audit trail are always visible regardless of which action
    happened most recently. `status` alone says which is current.

    While status='closed' for a period, the service layer (see
    app/services/salary_period_closure_service.py's `ensure_period_open`)
    blocks: Employee Credits dated in it, Salary Payments for it, Salary
    History revisions that could retroactively affect it, Attendance records
    dated in it, and create/update/delete of a *final* Fuel Entry dated in
    it (a final fuel entry's employee-credit side effect would otherwise
    reach back into a closed month through a different screen entirely).
    """

    __tablename__ = "Salary_Period_Closures"
    __table_args__ = (
        UniqueConstraint("period_year", "period_month", name="uq_salary_period_closures_period"),
        CheckConstraint("period_month BETWEEN 1 AND 12", name="ck_salary_period_closures_period_month"),
        CheckConstraint("status IN ('closed', 'open')", name="ck_salary_period_closures_status"),
    )

    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'closed'"))
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("Users.id", ondelete="SET NULL"))
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reopened_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Users.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)

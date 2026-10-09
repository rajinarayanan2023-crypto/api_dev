import calendar
from collections.abc import Sequence
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.models.employee import Employee, SalaryPeriodClosure
from app.models.user import User
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.salary_period_closure_repository import SalaryPeriodClosureRepository


def _period_label(period_year: int, period_month: int) -> str:
    return f"{calendar.month_name[period_month]} {period_year}"


def _month_bounds(period_year: int, period_month: int) -> tuple[date, date]:
    last_day = calendar.monthrange(period_year, period_month)[1]
    return date(period_year, period_month, 1), date(period_year, period_month, last_day)


async def _attach_closure_actor_names(session: AsyncSession, closures: Sequence[SalaryPeriodClosure]) -> None:
    """Same one-batch-query pattern as app/services/audit.py's
    attach_actor_names, scoped to this model's own closed_by/reopened_by
    pair instead of the generic created_by/updated_by — a closure's
    "who closed it" and "who reopened it" are two different people across
    two different actions, both worth showing regardless of which happened
    most recently (see SalaryPeriodClosure's own docstring).
    """
    ids = {
        getattr(c, field)
        for c in closures
        for field in ("closed_by", "reopened_by")
        if getattr(c, field, None) is not None
    }
    names: dict = {}
    if ids:
        result = await session.execute(select(User.id, User.name).where(User.id.in_(ids)))
        names = dict(result.all())
    for c in closures:
        c.closed_by_name = names.get(c.closed_by)
        c.reopened_by_name = names.get(c.reopened_by)


class SalaryPeriodClosureService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.closures = SalaryPeriodClosureRepository(session)

    async def list_all(self) -> list[SalaryPeriodClosure]:
        rows = await self.closures.list_all()
        await _attach_closure_actor_names(self.session, rows)
        return rows

    async def close_period(self, period_year: int, period_month: int, actor: User, note: str | None) -> SalaryPeriodClosure:
        await self.closures.lock_for_update(period_year, period_month)
        row = await self.closures.get_by_period(period_year, period_month)
        if row is not None and row.status == "closed":
            raise ConflictError(f"{_period_label(period_year, period_month)} is already closed.")

        now = datetime.now(timezone.utc)
        if row is None:
            row = SalaryPeriodClosure(
                period_year=period_year,
                period_month=period_month,
                status="closed",
                closed_at=now,
                closed_by=actor.id,
                created_by=actor.id,
                updated_by=actor.id,
                note=note,
            )
            self.session.add(row)
        else:
            row.status = "closed"
            row.closed_at = now
            row.closed_by = actor.id
            row.updated_by = actor.id
            if note is not None:
                row.note = note
        try:
            await self.session.flush()
        except IntegrityError as exc:
            # Two requests racing to close the same never-before-closed
            # period both pass the "does this exist" check above before
            # either has saved — the table's own unique constraint catches
            # the second one; without this, that surfaces as a raw 500
            # instead of the same clean message the first request would
            # have gotten if it had simply run a moment later.
            if "uq_salary_period_closures_period" in str(exc):
                raise ConflictError(f"{_period_label(period_year, period_month)} is already closed.") from exc
            raise
        await self.session.refresh(row)
        await _attach_closure_actor_names(self.session, [row])
        return row

    async def reopen_period(self, period_year: int, period_month: int, actor: User, note: str | None) -> SalaryPeriodClosure:
        await self.closures.lock_for_update(period_year, period_month)
        row = await self.closures.get_by_period(period_year, period_month)
        if row is None or row.status != "closed":
            raise ConflictError(f"{_period_label(period_year, period_month)} is not currently closed.")

        row.status = "open"
        row.reopened_at = datetime.now(timezone.utc)
        row.reopened_by = actor.id
        row.updated_by = actor.id
        if note is not None:
            row.note = note
        await self.session.flush()
        await self.session.refresh(row)
        await _attach_closure_actor_names(self.session, [row])
        return row

    async def ensure_period_open(self, period_year: int, period_month: int) -> None:
        """The actual lock check, called from every salary-affecting mutation
        (credits, payments, salary revisions, attendance, final fuel entries)
        before any write happens. Raises ConflictError, never returns a
        value — callers just await it and move on if the period is open.
        """
        row = await self.closures.get_by_period(period_year, period_month)
        if row is not None and row.status == "closed":
            raise ConflictError(
                f"{_period_label(period_year, period_month)} is closed for salary changes. "
                "Reopen it first to make this change."
            )

    async def ensure_no_closed_period_on_or_after(self, period_year: int, period_month: int) -> None:
        """Salary revisions are in-force-until-superseded: a new (or removed)
        revision effective on a given date also changes what's "in force" for
        every later month, not just its own. So adding/removing a revision
        must be blocked if ANY closed month falls on or after it — not just
        its own month — otherwise a change made through the revision screen
        could silently rewrite a closed month's payable figure.
        """
        rows = await self.closures.list_all()
        for row in rows:
            if row.status != "closed":
                continue
            if (row.period_year, row.period_month) >= (period_year, period_month):
                raise ConflictError(
                    f"{_period_label(row.period_year, row.period_month)} is closed, and this change would "
                    f"affect pay calculated for that month. Reopen {_period_label(row.period_year, row.period_month)} "
                    "first to make this change."
                )

    async def ensure_employee_deletable(self, employee: Employee, session: AsyncSession) -> None:
        """Deleting an employee cascades away ALL of their salary history,
        credits, and payments (see Employee.salary_history/credits/payments
        relationships' cascade="all, delete-orphan") — closing a period only
        guards editing ONE record at a time, so without this, deleting the
        whole employee would silently take a closed, supposedly-protected
        month's data down with it. Blocks the delete entirely if the employee
        has anything touching a closed period, same "reopen it first" shape
        as every other guard here.
        """
        rows = await self.closures.list_all()
        closed = [row for row in rows if row.status == "closed"]
        if not closed:
            return

        earliest_revision = min((h.effective_from for h in employee.salary_history), default=None)
        attendance = AttendanceRepository(session)
        for row in closed:
            label = _period_label(row.period_year, row.period_month)
            start, end = _month_bounds(row.period_year, row.period_month)

            if earliest_revision is not None and (row.period_year, row.period_month) >= (
                earliest_revision.year,
                earliest_revision.month,
            ):
                raise ConflictError(
                    f"Cannot delete this employee — {label} is closed and this employee has salary "
                    f"history affecting it. Reopen {label} first."
                )
            if any(start <= credit.date <= end for credit in employee.credits):
                raise ConflictError(
                    f"Cannot delete this employee — they have a credit or repayment dated in {label}, "
                    f"which is closed. Reopen {label} first."
                )
            if any(p.period_year == row.period_year and p.period_month == row.period_month for p in employee.payments):
                raise ConflictError(
                    f"Cannot delete this employee — they have a salary payment recorded for {label}, "
                    f"which is closed. Reopen {label} first."
                )
            if await attendance.list_for_employee_in_range(employee.id, start, end):
                raise ConflictError(
                    f"Cannot delete this employee — they have attendance recorded in {label}, which is "
                    f"closed. Reopen {label} first."
                )

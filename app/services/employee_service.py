import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.employee import Employee, EmployeeCredit, EmployeeSalaryHistory, SalaryPayment
from app.models.user import User
from app.repositories.employee_repository import EmployeeRepository
from app.schemas.employee import (
    EmployeeCreate,
    EmployeeCreditCreate,
    EmployeeCreditUpdate,
    EmployeeUpdate,
    SalaryHistoryCreate,
    SalaryPaymentCreate,
    SalaryPaymentUpdate,
)
from app.services.audit import attach_actor_names
from app.services.salary_period_closure_service import SalaryPeriodClosureService


class EmployeeService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.employees = EmployeeRepository(session)
        self.period_closures = SalaryPeriodClosureService(session)

    async def create_employee(self, data: EmployeeCreate, actor: User) -> Employee:
        if await self.employees.get_by_name_and_father_name(data.name, data.father_name) is not None:
            raise ConflictError("An employee with this same name and father's name already exists.")
        if data.phone and await self.employees.get_by_phone(data.phone) is not None:
            raise ConflictError("This phone number is already used by another employee.")
        # A backdated join_date's starting salary is in force from that date
        # onward same as any other revision — block it the same way if it
        # would reach into an already-closed month (see add_salary_revision).
        await self.period_closures.ensure_no_closed_period_on_or_after(data.join_date.year, data.join_date.month)

        payload = data.model_dump(exclude={"starting_salary"})
        employee = Employee(**payload, created_by=actor.id, updated_by=actor.id)
        employee.salary_history = [
            EmployeeSalaryHistory(
                effective_from=data.join_date,
                amount=data.starting_salary,
                created_by=actor.id,
                updated_by=actor.id,
            )
        ]
        try:
            created = await self.employees.create(employee)
        except IntegrityError as exc:
            # Two "create employee" requests racing at the same instant both
            # pass the name+father's-name check above before either has
            # saved — the database's own case-insensitive unique index
            # catches the second one; without this, that surfaces as a raw
            # 500 instead of the same clean message the check above already
            # gives the common (non-racing) case.
            if "uq_employees_name_father_name_ci" in str(exc):
                raise ConflictError("An employee with this same name and father's name already exists.") from exc
            raise
        # BaseRepository.create()'s refresh() expires (but does not eagerly
        # reload) relationship attributes, which would otherwise force a
        # lazy-load during Pydantic's synchronous serialization — something
        # AsyncSession can't service outside an active await. Re-fetch with
        # salary_history eagerly loaded instead.
        return await self.get_employee(created.id)

    async def list_employees(self, offset: int = 0, limit: int = 100) -> list[Employee]:
        employees = await self.employees.list_with_salary_history(offset=offset, limit=limit)
        await attach_actor_names(self.session, employees)
        await attach_actor_names(self.session, [c for e in employees for c in e.credits])
        await attach_actor_names(self.session, [p for e in employees for p in e.payments])
        await attach_actor_names(self.session, [h for e in employees for h in e.salary_history])
        return employees

    async def get_employee(self, employee_id: uuid.UUID) -> Employee:
        employee = await self.employees.get_with_salary_history(employee_id)
        if employee is None:
            raise NotFoundError("Employee not found.")
        await attach_actor_names(self.session, [employee])
        await attach_actor_names(self.session, employee.credits)
        await attach_actor_names(self.session, employee.payments)
        await attach_actor_names(self.session, employee.salary_history)
        return employee

    async def update_employee(self, employee_id: uuid.UUID, data: EmployeeUpdate, actor: User) -> Employee:
        employee = await self.get_employee(employee_id)
        updates = data.model_dump(exclude_unset=True)

        # join_date is in force from that date onward exactly like a salary
        # revision's effective_from (see create_employee's own comment) — a
        # backdated edit here needs the same ripple-forward guard, which this
        # method was missing entirely until now. Only guards an ACTUAL change
        # — Employees.jsx's edit form always resends join_date even when the
        # user never touched it, and that must stay a no-op (not a 409) once
        # any period is ever closed, or every unrelated edit (phone, notes,
        # role) on every employee would start failing right along with it.
        if "join_date" in updates and updates["join_date"] != employee.join_date:
            await self.period_closures.ensure_no_closed_period_on_or_after(
                updates["join_date"].year, updates["join_date"].month
            )

        if "name" in updates or "father_name" in updates:
            new_name = updates.get("name", employee.name)
            new_father_name = updates.get("father_name", employee.father_name)
            existing = await self.employees.get_by_name_and_father_name(new_name, new_father_name, exclude_id=employee.id)
            if existing is not None:
                raise ConflictError("An employee with this same name and father's name already exists.")
        if updates.get("phone"):
            existing = await self.employees.get_by_phone(updates["phone"], exclude_id=employee.id)
            if existing is not None:
                raise ConflictError("This phone number is already used by another employee.")

        for field, value in updates.items():
            setattr(employee, field, value)
        if updates:
            employee.updated_by = actor.id
        try:
            await self.session.flush()
        except IntegrityError as exc:
            if "uq_employees_name_father_name_ci" in str(exc):
                raise ConflictError("An employee with this same name and father's name already exists.") from exc
            raise
        if updates:
            # Refresh only the columns just written — an unqualified
            # refresh() also expires (without reloading) relationship
            # attributes like salary_history, which would then crash
            # Pydantic serialization by forcing a lazy-load outside an
            # active await.
            await self.session.refresh(employee, attribute_names=[*updates.keys(), "updated_by", "updated_at"])
        await attach_actor_names(self.session, [employee])
        return employee

    # Replaces the existing row instead of inserting a duplicate when
    # effective_from matches one already on record (e.g. a same-day correction
    # to a brand-new hire's starting salary) — the table has a unique
    # constraint on (employee_id, effective_from), so a plain insert would
    # otherwise raise IntegrityError for what the manager sees as an edit.
    async def add_salary_revision(self, employee_id: uuid.UUID, data: SalaryHistoryCreate, actor: User) -> Employee:
        employee = await self.get_employee(employee_id)
        # A revision is in force from its date onward until superseded, so it
        # can retroactively change pay for every later month too, not just its
        # own — block it if that reach touches any closed month.
        await self.period_closures.ensure_no_closed_period_on_or_after(
            data.effective_from.year, data.effective_from.month
        )
        existing = next((h for h in employee.salary_history if h.effective_from == data.effective_from), None)
        if existing is not None:
            existing.amount = data.amount
            existing.updated_by = actor.id
            employee.updated_by = actor.id
            await self.session.flush()
        else:
            revision = EmployeeSalaryHistory(
                employee_id=employee.id,
                effective_from=data.effective_from,
                amount=data.amount,
                created_by=actor.id,
                updated_by=actor.id,
            )
            try:
                await self.employees.add_salary_revision(revision)
            except IntegrityError as exc:
                # Two requests racing to add the first-ever revision for the
                # same (employee, effective_from) both pass the "existing is
                # None" check above before either has saved — the table's own
                # unique constraint catches the second one; without this, that
                # surfaces as a raw 500 instead of a clean message.
                if "uq_employee_salary_history" in str(exc):
                    raise ConflictError(
                        "A salary revision for this employee effective on this date was just added. Refresh and try again."
                    ) from exc
                raise
            employee.updated_by = actor.id
            await self.session.flush()
            # The new row went in through a separate object, not through
            # employee.salary_history itself, so that already-loaded
            # collection is now stale in the session's identity map — expire
            # it so get_employee() below actually re-reads it from the DB
            # instead of returning the cached (pre-insert) collection.
            self.session.expire(employee, ["salary_history"])
        return await self.get_employee(employee_id)

    # Salary history is otherwise append-only (see add_salary_revision's own
    # upsert-by-date comment above) — this is deliberately the one way out
    # for a revision added with the wrong amount AND the wrong date, where
    # the upsert-by-date trick above can't reach it (that only overwrites an
    # entry sharing the SAME effective_from). Blocked on the last remaining
    # entry: an employee always needs at least one row to derive "current
    # pay" from (see sortedSalaryHistory/currentSalary on the frontend).
    async def delete_salary_revision(self, employee_id: uuid.UUID, revision_id: uuid.UUID) -> Employee:
        employee = await self.get_employee(employee_id)
        revision = next((h for h in employee.salary_history if h.id == revision_id), None)
        if revision is None:
            raise NotFoundError("Salary revision not found.")
        if len(employee.salary_history) <= 1:
            raise ConflictError("An employee must have at least one salary revision on record.")
        await self.period_closures.ensure_no_closed_period_on_or_after(
            revision.effective_from.year, revision.effective_from.month
        )
        employee.salary_history.remove(revision)
        await self.session.flush()
        self.session.expire(employee, ["salary_history"])
        return await self.get_employee(employee_id)

    async def delete_employee(self, employee_id: uuid.UUID) -> None:
        employee = await self.get_employee(employee_id)
        await self.period_closures.ensure_employee_deletable(employee, self.session)
        await self.employees.delete(employee)

    async def add_credit(self, employee_id: uuid.UUID, data: EmployeeCreditCreate, actor: User) -> Employee:
        employee = await self.get_employee(employee_id)
        await self.period_closures.ensure_period_open(data.date.year, data.date.month)
        # Appending to the relationship (rather than session.add() with
        # employee_id set directly) keeps the already-loaded employee.credits
        # collection in sync in memory — a plain add() still inserts the row
        # correctly, but the subsequent get_employee() below would otherwise
        # return the stale (pre-insert) cached collection.
        employee.credits.append(
            EmployeeCredit(
                date=data.date, amount=data.amount, type=data.type, note=data.note, created_by=actor.id, updated_by=actor.id
            )
        )
        employee.updated_by = actor.id
        await self.session.flush()
        return await self.get_employee(employee_id)

    def _get_manual_credit(self, employee: Employee, credit_id: uuid.UUID) -> EmployeeCredit:
        credit = next((c for c in employee.credits if c.id == credit_id), None)
        if credit is None:
            raise NotFoundError("Employee credit not found.")
        if credit.source_fuel_entry_id is not None:
            raise ConflictError("This credit was created from a Fuel Entry and can't be changed directly.")
        return credit

    async def update_credit(
        self, employee_id: uuid.UUID, credit_id: uuid.UUID, data: EmployeeCreditUpdate, actor: User
    ) -> Employee:
        employee = await self.get_employee(employee_id)
        credit = self._get_manual_credit(employee, credit_id)
        updates = data.model_dump(exclude_unset=True)
        # Check both the credit's current period (can't touch one sitting in a
        # closed month) and its incoming period if the date is moving (can't
        # move one into a closed month either) — same date hits the guard once.
        for check_date in {credit.date, updates.get("date", credit.date)}:
            await self.period_closures.ensure_period_open(check_date.year, check_date.month)
        for field, value in updates.items():
            setattr(credit, field, value)
        if updates:
            credit.updated_by = actor.id
            employee.updated_by = actor.id
        await self.session.flush()
        return await self.get_employee(employee_id)

    async def delete_credit(self, employee_id: uuid.UUID, credit_id: uuid.UUID) -> None:
        employee = await self.get_employee(employee_id)
        credit = self._get_manual_credit(employee, credit_id)
        await self.period_closures.ensure_period_open(credit.date.year, credit.date.month)
        employee.credits.remove(credit)
        await self.session.flush()

    # payable_snapshot is computed and sent by the caller (Salary.jsx reads
    # it straight off the same live utils/salary.js figure already on
    # screen) — never recomputed here, since the whole point is to freeze
    # what "payable" showed at the moment of payment, immune to a later edit
    # to that period's attendance/credits (see SalaryPayment's own
    # docstring). A null snapshot just means the caller didn't have one to
    # send (e.g. a backfilled historical payment).
    async def add_payment(self, employee_id: uuid.UUID, data: SalaryPaymentCreate, actor: User) -> Employee:
        employee = await self.get_employee(employee_id)
        await self.period_closures.ensure_period_open(data.period_year, data.period_month)
        # Appending to the relationship (not a bare session.add()) keeps the
        # already-loaded employee.payments collection in sync in memory —
        # same reasoning as add_credit above.
        employee.payments.append(
            SalaryPayment(
                period_year=data.period_year,
                period_month=data.period_month,
                amount_paid=data.amount_paid,
                payable_snapshot=data.payable_snapshot,
                paid_date=data.paid_date,
                note=data.note,
                created_by=actor.id,
                updated_by=actor.id,
            )
        )
        employee.updated_by = actor.id
        await self.session.flush()
        return await self.get_employee(employee_id)

    def _get_payment(self, employee: Employee, payment_id: uuid.UUID) -> SalaryPayment:
        payment = next((p for p in employee.payments if p.id == payment_id), None)
        if payment is None:
            raise NotFoundError("Salary payment not found.")
        return payment

    async def update_payment(
        self, employee_id: uuid.UUID, payment_id: uuid.UUID, data: SalaryPaymentUpdate, actor: User
    ) -> Employee:
        employee = await self.get_employee(employee_id)
        payment = self._get_payment(employee, payment_id)
        updates = data.model_dump(exclude_unset=True)
        # Check both the payment's current period and its incoming period if
        # either period field is moving — same reasoning as update_credit above.
        new_year = updates.get("period_year", payment.period_year)
        new_month = updates.get("period_month", payment.period_month)
        for year, month in {(payment.period_year, payment.period_month), (new_year, new_month)}:
            await self.period_closures.ensure_period_open(year, month)
        for field, value in updates.items():
            setattr(payment, field, value)
        if updates:
            payment.updated_by = actor.id
            employee.updated_by = actor.id
        await self.session.flush()
        return await self.get_employee(employee_id)

    async def delete_payment(self, employee_id: uuid.UUID, payment_id: uuid.UUID) -> None:
        employee = await self.get_employee(employee_id)
        payment = self._get_payment(employee, payment_id)
        await self.period_closures.ensure_period_open(payment.period_year, payment.period_month)
        employee.payments.remove(payment)
        await self.session.flush()

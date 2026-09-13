import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.employee import Employee, EmployeeCredit, EmployeeSalaryHistory
from app.models.user import User
from app.repositories.employee_repository import EmployeeRepository
from app.schemas.employee import EmployeeCreate, EmployeeCreditCreate, EmployeeCreditUpdate, EmployeeUpdate, SalaryHistoryCreate
from app.services.audit import attach_actor_names


class EmployeeService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.employees = EmployeeRepository(session)

    async def create_employee(self, data: EmployeeCreate, actor: User) -> Employee:
        if await self.employees.get_by_name_and_father_name(data.name, data.father_name) is not None:
            raise ConflictError("An employee with this same name and father's name already exists.")
        if data.phone and await self.employees.get_by_phone(data.phone) is not None:
            raise ConflictError("This phone number is already used by another employee.")

        payload = data.model_dump(exclude={"starting_salary"})
        employee = Employee(**payload, created_by=actor.id, updated_by=actor.id)
        employee.salary_history = [
            EmployeeSalaryHistory(effective_from=data.join_date, amount=data.starting_salary)
        ]
        created = await self.employees.create(employee)
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
        return employees

    async def get_employee(self, employee_id: uuid.UUID) -> Employee:
        employee = await self.employees.get_with_salary_history(employee_id)
        if employee is None:
            raise NotFoundError("Employee not found.")
        await attach_actor_names(self.session, [employee])
        await attach_actor_names(self.session, employee.credits)
        return employee

    async def update_employee(self, employee_id: uuid.UUID, data: EmployeeUpdate, actor: User) -> Employee:
        employee = await self.get_employee(employee_id)
        updates = data.model_dump(exclude_unset=True)

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
        await self.session.flush()
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
        existing = next((h for h in employee.salary_history if h.effective_from == data.effective_from), None)
        if existing is not None:
            existing.amount = data.amount
            employee.updated_by = actor.id
            await self.session.flush()
        else:
            revision = EmployeeSalaryHistory(
                employee_id=employee.id, effective_from=data.effective_from, amount=data.amount
            )
            await self.employees.add_salary_revision(revision)
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
        employee.salary_history.remove(revision)
        await self.session.flush()
        self.session.expire(employee, ["salary_history"])
        return await self.get_employee(employee_id)

    async def delete_employee(self, employee_id: uuid.UUID) -> None:
        employee = await self.get_employee(employee_id)
        await self.employees.delete(employee)

    async def add_credit(self, employee_id: uuid.UUID, data: EmployeeCreditCreate, actor: User) -> Employee:
        employee = await self.get_employee(employee_id)
        # Appending to the relationship (rather than session.add() with
        # employee_id set directly) keeps the already-loaded employee.credits
        # collection in sync in memory — a plain add() still inserts the row
        # correctly, but the subsequent get_employee() below would otherwise
        # return the stale (pre-insert) cached collection.
        employee.credits.append(
            EmployeeCredit(date=data.date, amount=data.amount, note=data.note, created_by=actor.id, updated_by=actor.id)
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
        employee.credits.remove(credit)
        await self.session.flush()

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.employee import Employee, EmployeeSalaryHistory
from app.models.user import User
from app.repositories.employee_repository import EmployeeRepository
from app.schemas.employee import EmployeeCreate, EmployeeUpdate, SalaryHistoryCreate
from app.services.audit import attach_actor_names


class EmployeeService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.employees = EmployeeRepository(session)

    async def create_employee(self, data: EmployeeCreate, actor: User) -> Employee:
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
        return employees

    async def get_employee(self, employee_id: uuid.UUID) -> Employee:
        employee = await self.employees.get_with_salary_history(employee_id)
        if employee is None:
            raise NotFoundError("Employee not found.")
        await attach_actor_names(self.session, [employee])
        return employee

    async def update_employee(self, employee_id: uuid.UUID, data: EmployeeUpdate, actor: User) -> Employee:
        employee = await self.get_employee(employee_id)
        updates = data.model_dump(exclude_unset=True)
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
        return await self.get_employee(employee_id)

    async def delete_employee(self, employee_id: uuid.UUID) -> None:
        employee = await self.get_employee(employee_id)
        await self.employees.delete(employee)

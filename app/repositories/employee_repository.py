import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.employee import Employee, EmployeeSalaryHistory
from app.repositories.base import BaseRepository

_WITH_DETAIL = (selectinload(Employee.salary_history), selectinload(Employee.credits))


class EmployeeRepository(BaseRepository[Employee]):
    def __init__(self, session: AsyncSession):
        super().__init__(Employee, session)

    # name + father_name together is what actually identifies a person
    # (matches the UI's own client-side check) — same first name alone is
    # common in a small crew and isn't a real collision on its own. Case/
    # whitespace-insensitive; a missing father_name on both sides (NULL,
    # via coalesce) still counts as a match rather than as "different".
    async def get_by_name_and_father_name(
        self, name: str, father_name: str | None, exclude_id: uuid.UUID | None = None
    ) -> Employee | None:
        query = select(Employee).where(
            func.lower(Employee.name) == name.strip().lower(),
            func.lower(func.coalesce(Employee.father_name, "")) == (father_name or "").strip().lower(),
        )
        if exclude_id is not None:
            query = query.where(Employee.id != exclude_id)
        result = await self.session.execute(query)
        return result.scalars().first()

    async def get_by_phone(self, phone: str, exclude_id: uuid.UUID | None = None) -> Employee | None:
        query = select(Employee).where(Employee.phone == phone)
        if exclude_id is not None:
            query = query.where(Employee.id != exclude_id)
        result = await self.session.execute(query)
        return result.scalars().first()

    async def get_with_salary_history(self, id: uuid.UUID) -> Employee | None:
        result = await self.session.execute(select(Employee).options(*_WITH_DETAIL).where(Employee.id == id))
        return result.scalar_one_or_none()

    async def list_with_salary_history(self, offset: int = 0, limit: int = 100) -> list[Employee]:
        result = await self.session.execute(select(Employee).options(*_WITH_DETAIL).offset(offset).limit(limit))
        return list(result.scalars().all())

    async def add_salary_revision(self, revision: EmployeeSalaryHistory) -> EmployeeSalaryHistory:
        self.session.add(revision)
        await self.session.flush()
        await self.session.refresh(revision)
        return revision

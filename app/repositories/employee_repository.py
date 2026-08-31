import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.employee import Employee, EmployeeSalaryHistory
from app.repositories.base import BaseRepository

_WITH_DETAIL = (selectinload(Employee.salary_history), selectinload(Employee.credits))


class EmployeeRepository(BaseRepository[Employee]):
    def __init__(self, session: AsyncSession):
        super().__init__(Employee, session)

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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.expense import ExpenseDay
from app.repositories.base import BaseRepository


class ExpenseDayRepository(BaseRepository[ExpenseDay]):
    def __init__(self, session: AsyncSession):
        super().__init__(ExpenseDay, session)

    async def get_with_items(self, id):
        result = await self.session.execute(
            select(ExpenseDay).options(selectinload(ExpenseDay.items)).where(ExpenseDay.id == id)
        )
        return result.scalar_one_or_none()

    async def get_by_date(self, day):
        result = await self.session.execute(select(ExpenseDay).where(ExpenseDay.date == day))
        return result.scalar_one_or_none()

    async def list_with_items(self, offset: int = 0, limit: int = 200) -> list[ExpenseDay]:
        result = await self.session.execute(
            select(ExpenseDay)
            .options(selectinload(ExpenseDay.items))
            .order_by(ExpenseDay.date.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

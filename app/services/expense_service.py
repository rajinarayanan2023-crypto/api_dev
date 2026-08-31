import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.expense import ExpenseDay, ExpenseItem
from app.models.user import User
from app.repositories.expense_repository import ExpenseDayRepository
from app.schemas.expense import ExpenseDayCreate, ExpenseDayUpdate
from app.services.audit import attach_actor_names


class ExpenseService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.expense_days = ExpenseDayRepository(session)

    async def create_expense_day(self, data: ExpenseDayCreate, actor: User) -> ExpenseDay:
        existing = await self.expense_days.get_by_date(data.date)
        if existing is not None:
            raise ConflictError("An expense record for this date already exists.")

        day = ExpenseDay(date=data.date, created_by=actor.id, updated_by=actor.id)
        day.items = [ExpenseItem(label=item.label, amount=item.amount) for item in data.items]
        created = await self.expense_days.create(day)
        return await self.get_expense_day(created.id)

    async def list_expense_days(self, offset: int = 0, limit: int = 200) -> list[ExpenseDay]:
        days = await self.expense_days.list_with_items(offset=offset, limit=limit)
        await attach_actor_names(self.session, days)
        return days

    async def get_expense_day(self, expense_day_id: uuid.UUID) -> ExpenseDay:
        day = await self.expense_days.get_with_items(expense_day_id)
        if day is None:
            raise NotFoundError("Expense record not found.")
        await attach_actor_names(self.session, [day])
        return day

    async def update_expense_day(self, expense_day_id: uuid.UUID, data: ExpenseDayUpdate, actor: User) -> ExpenseDay:
        day = await self.get_expense_day(expense_day_id)

        if data.date != day.date:
            existing = await self.expense_days.get_by_date(data.date)
            if existing is not None and existing.id != day.id:
                raise ConflictError("An expense record for this date already exists.")
            day.date = data.date

        # Full replace — the UI resubmits the whole item list on every save
        # rather than incremental patches; the ORM cascade
        # ("all, delete-orphan") deletes whatever's removed from the collection.
        day.items = [ExpenseItem(label=item.label, amount=item.amount) for item in data.items]
        day.updated_by = actor.id
        await self.session.flush()
        return await self.get_expense_day(expense_day_id)

    async def delete_expense_day(self, expense_day_id: uuid.UUID) -> None:
        day = await self.get_expense_day(expense_day_id)
        await self.expense_days.delete(day)

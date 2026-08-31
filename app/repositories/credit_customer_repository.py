import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.credit import CreditCustomer
from app.repositories.base import BaseRepository

_WITH_DETAIL = (
    selectinload(CreditCustomer.ledger_entries),
    selectinload(CreditCustomer.bills),
)


class CreditCustomerRepository(BaseRepository[CreditCustomer]):
    def __init__(self, session: AsyncSession):
        super().__init__(CreditCustomer, session)

    async def get_with_details(self, id: uuid.UUID) -> CreditCustomer | None:
        result = await self.session.execute(select(CreditCustomer).options(*_WITH_DETAIL).where(CreditCustomer.id == id))
        return result.scalar_one_or_none()

    async def list_with_details(self, offset: int = 0, limit: int = 500) -> list[CreditCustomer]:
        result = await self.session.execute(
            select(CreditCustomer).options(*_WITH_DETAIL).order_by(CreditCustomer.name).offset(offset).limit(limit)
        )
        return list(result.scalars().all())

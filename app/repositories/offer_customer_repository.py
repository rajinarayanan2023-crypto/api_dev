from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.offer import OfferCustomer
from app.repositories.base import BaseRepository


class OfferCustomerRepository(BaseRepository[OfferCustomer]):
    def __init__(self, session: AsyncSession):
        super().__init__(OfferCustomer, session)

    async def list_all(self, offset: int = 0, limit: int = 500) -> list[OfferCustomer]:
        result = await self.session.execute(
            select(OfferCustomer).order_by(OfferCustomer.name).offset(offset).limit(limit)
        )
        return list(result.scalars().all())

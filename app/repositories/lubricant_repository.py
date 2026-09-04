import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.lubricant import LubricantProduct, LubricantPurchaseHistory, LubricantPriceHistory
from app.repositories.base import BaseRepository

_WITH_HISTORY = (
    selectinload(LubricantProduct.price_history),
    selectinload(LubricantProduct.purchase_history),
)


class LubricantRepository(BaseRepository[LubricantProduct]):
    def __init__(self, session: AsyncSession):
        super().__init__(LubricantProduct, session)

    async def get_by_name_ci(self, name: str) -> LubricantProduct | None:
        result = await self.session.execute(
            select(LubricantProduct).where(func.lower(LubricantProduct.name) == name.strip().lower())
        )
        return result.scalars().first()

    async def get_with_history(self, id: uuid.UUID) -> LubricantProduct | None:
        result = await self.session.execute(
            select(LubricantProduct).options(*_WITH_HISTORY).where(LubricantProduct.id == id)
        )
        return result.scalar_one_or_none()

    async def list_with_history(self, offset: int = 0, limit: int = 100) -> list[LubricantProduct]:
        result = await self.session.execute(
            select(LubricantProduct).options(*_WITH_HISTORY).offset(offset).limit(limit)
        )
        return list(result.scalars().all())

    async def add_price_revision(self, revision: LubricantPriceHistory) -> LubricantPriceHistory:
        self.session.add(revision)
        await self.session.flush()
        await self.session.refresh(revision)
        return revision

    async def add_purchase(self, purchase: LubricantPurchaseHistory) -> LubricantPurchaseHistory:
        self.session.add(purchase)
        await self.session.flush()
        await self.session.refresh(purchase)
        return purchase

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.offer import OfferSend
from app.repositories.base import BaseRepository


class OfferSendRepository(BaseRepository[OfferSend]):
    def __init__(self, session: AsyncSession):
        super().__init__(OfferSend, session)

    async def get_with_recipients(self, id) -> OfferSend | None:
        result = await self.session.execute(
            select(OfferSend).options(selectinload(OfferSend.recipients)).where(OfferSend.id == id)
        )
        return result.scalar_one_or_none()

    async def list_with_recipients(self, offset: int = 0, limit: int = 100) -> list[OfferSend]:
        result = await self.session.execute(
            select(OfferSend)
            .options(selectinload(OfferSend.recipients))
            .order_by(OfferSend.sent_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.station import Station
from app.repositories.base import BaseRepository


class StationRepository(BaseRepository[Station]):
    def __init__(self, session: AsyncSession):
        super().__init__(Station, session)

    async def get_singleton(self) -> Station | None:
        result = await self.session.execute(select(Station).limit(1))
        return result.scalar_one_or_none()

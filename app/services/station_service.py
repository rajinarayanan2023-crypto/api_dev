from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFoundError
from app.models.station import Station
from app.models.user import User
from app.repositories.station_repository import StationRepository
from app.schemas.station import StationUpdate
from app.services.audit import attach_actor_names


class StationService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.stations = StationRepository(session)

    async def get_station(self) -> Station:
        station = await self.stations.get_singleton()
        if station is None:
            raise NotFoundError("Station profile has not been set up yet.")
        await attach_actor_names(self.session, [station])
        return station

    async def upsert_station(self, data: StationUpdate, actor: User) -> Station:
        station = await self.stations.get_singleton()
        payload = data.model_dump(exclude_unset=True)

        if station is None:
            if not payload.get("name"):
                raise AppError("name is required when creating the station profile for the first time.")
            station = Station(**payload, created_by=actor.id, updated_by=actor.id)
            created = await self.stations.create(station)
            await attach_actor_names(self.session, [created])
            return created

        for field, value in payload.items():
            setattr(station, field, value)
        station.updated_by = actor.id
        await self.session.flush()
        await self.session.refresh(station)
        await attach_actor_names(self.session, [station])
        return station

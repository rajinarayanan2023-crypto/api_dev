from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db_session, require_manager_or_admin
from app.models.user import User
from app.schemas.station import StationOut, StationUpdate
from app.services.station_service import StationService

router = APIRouter(prefix="/station", tags=["station"])


@router.get("", response_model=StationOut, dependencies=[Depends(get_current_active_user)])
async def get_station(session: AsyncSession = Depends(get_db_session)) -> StationOut:
    service = StationService(session)
    station = await service.get_station()
    return StationOut.model_validate(station)


@router.put("", response_model=StationOut)
async def update_station(
    body: StationUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_manager_or_admin),
) -> StationOut:
    service = StationService(session)
    station = await service.upsert_station(body, current_user)
    return StationOut.model_validate(station)

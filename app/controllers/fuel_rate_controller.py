import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db_session, require_manager_or_admin
from app.models.user import User
from app.schemas.common import Message
from app.schemas.fuel_rate import FuelRateCreate, FuelRateOut
from app.services.fuel_rate_service import FuelRateService

router = APIRouter(prefix="/fuel-rates", tags=["fuel-rates"], dependencies=[Depends(get_current_active_user)])


@router.post("", response_model=FuelRateOut, status_code=status.HTTP_201_CREATED)
async def create_or_revise_rate(
    body: FuelRateCreate,
    current_user: User = Depends(require_manager_or_admin),
    session: AsyncSession = Depends(get_db_session),
) -> FuelRateOut:
    service = FuelRateService(session)
    rate = await service.create_or_revise(body, current_user)
    return FuelRateOut.model_validate(rate)


@router.get("/current", response_model=FuelRateOut)
async def get_current_rate(
    as_of: date | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
) -> FuelRateOut:
    service = FuelRateService(session)
    rate = await service.get_current(as_of)
    return FuelRateOut.model_validate(rate)


@router.get("", response_model=list[FuelRateOut])
async def list_rates(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=1000),
    session: AsyncSession = Depends(get_db_session),
) -> list[FuelRateOut]:
    service = FuelRateService(session)
    rates = await service.list_all(offset=offset, limit=limit)
    return [FuelRateOut.model_validate(r) for r in rates]


@router.delete("/{rate_id}", response_model=Message, dependencies=[Depends(require_manager_or_admin)])
async def delete_rate(rate_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> Message:
    service = FuelRateService(session)
    await service.delete(rate_id)
    return Message(detail="Fuel rate revision deleted.")

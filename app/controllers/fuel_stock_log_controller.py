import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db_session, require_manager_or_admin
from app.models.user import User
from app.schemas.common import Message
from app.schemas.fuel_stock_log import FuelStockLogCreate, FuelStockLogOut
from app.services.fuel_stock_log_service import FuelStockLogService

router = APIRouter(
    prefix="/fuel-stock-logs", tags=["fuel-stock-logs"], dependencies=[Depends(get_current_active_user)]
)


@router.post("", response_model=FuelStockLogOut, status_code=status.HTTP_201_CREATED)
async def create_or_revise_log(
    body: FuelStockLogCreate,
    current_user: User = Depends(require_manager_or_admin),
    session: AsyncSession = Depends(get_db_session),
) -> FuelStockLogOut:
    service = FuelStockLogService(session)
    log = await service.create_or_revise(body, current_user)
    return FuelStockLogOut.model_validate(log)


@router.get("", response_model=list[FuelStockLogOut])
async def list_logs(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=1000),
    session: AsyncSession = Depends(get_db_session),
) -> list[FuelStockLogOut]:
    service = FuelStockLogService(session)
    logs = await service.list_all(offset=offset, limit=limit)
    return [FuelStockLogOut.model_validate(l) for l in logs]


@router.delete("/{log_id}", response_model=Message, dependencies=[Depends(require_manager_or_admin)])
async def delete_log(log_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> Message:
    service = FuelStockLogService(session)
    await service.delete(log_id)
    return Message(detail="Fuel stock log deleted.")

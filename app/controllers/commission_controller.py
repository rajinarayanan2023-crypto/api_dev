from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db_session, require_manager_or_admin
from app.models.user import User
from app.schemas.commission import CommissionRateCreate, CommissionRateOut
from app.services.commission_service import CommissionRateService

router = APIRouter(
    prefix="/commission-rates", tags=["commission-rates"], dependencies=[Depends(get_current_active_user)]
)


@router.post(
    "", response_model=CommissionRateOut, status_code=status.HTTP_201_CREATED,
)
async def create_or_revise_rate(
    body: CommissionRateCreate,
    current_user: User = Depends(require_manager_or_admin),
    session: AsyncSession = Depends(get_db_session),
) -> CommissionRateOut:
    service = CommissionRateService(session)
    rate = await service.create_or_revise(body, current_user)
    return CommissionRateOut.model_validate(rate)


@router.get("/current", response_model=CommissionRateOut)
async def get_current_rate(
    as_of: date | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
) -> CommissionRateOut:
    service = CommissionRateService(session)
    rate = await service.get_current(as_of)
    return CommissionRateOut.model_validate(rate)


@router.get("", response_model=list[CommissionRateOut])
async def list_rates(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
) -> list[CommissionRateOut]:
    service = CommissionRateService(session)
    rates = await service.list_all(offset=offset, limit=limit)
    return [CommissionRateOut.model_validate(r) for r in rates]

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db_session, require_manager_or_admin
from app.models.user import User
from app.schemas.offer import OfferSendCreate, OfferSendOut
from app.services.offer_service import OfferService

router = APIRouter(prefix="/offers", tags=["offers"], dependencies=[Depends(get_current_active_user)])


@router.post("", response_model=OfferSendOut, status_code=status.HTTP_201_CREATED)
async def send_offer(
    body: OfferSendCreate,
    current_user: User = Depends(require_manager_or_admin),
    session: AsyncSession = Depends(get_db_session),
) -> OfferSendOut:
    service = OfferService(session)
    send = await service.send(body, current_user)
    return OfferSendOut.model_validate(send)


@router.get("", response_model=list[OfferSendOut])
async def list_offer_sends(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
) -> list[OfferSendOut]:
    service = OfferService(session)
    sends = await service.list_all(offset=offset, limit=limit)
    return [OfferSendOut.model_validate(s) for s in sends]

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db_session, require_manager_or_admin
from app.schemas.offer_customer import OfferCustomerCreate, OfferCustomerOut, OfferCustomerUpdate
from app.services.offer_customer_service import OfferCustomerService

router = APIRouter(prefix="/offer-customers", tags=["offer-customers"], dependencies=[Depends(get_current_active_user)])


@router.get("", response_model=list[OfferCustomerOut])
async def list_offer_customers(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=1000),
    session: AsyncSession = Depends(get_db_session),
) -> list[OfferCustomerOut]:
    service = OfferCustomerService(session)
    customers = await service.list_all(offset=offset, limit=limit)
    return [OfferCustomerOut.model_validate(c) for c in customers]


@router.post("", response_model=OfferCustomerOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_manager_or_admin)])
async def create_offer_customer(
    body: OfferCustomerCreate,
    session: AsyncSession = Depends(get_db_session),
) -> OfferCustomerOut:
    service = OfferCustomerService(session)
    customer = await service.create(body)
    return OfferCustomerOut.model_validate(customer)


@router.patch("/{customer_id}", response_model=OfferCustomerOut, dependencies=[Depends(require_manager_or_admin)])
async def update_offer_customer(
    customer_id: uuid.UUID,
    body: OfferCustomerUpdate,
    session: AsyncSession = Depends(get_db_session),
) -> OfferCustomerOut:
    service = OfferCustomerService(session)
    customer = await service.update(customer_id, body)
    return OfferCustomerOut.model_validate(customer)

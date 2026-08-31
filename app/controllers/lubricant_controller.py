import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db_session, require_manager_or_admin
from app.models.user import User
from app.schemas.common import Message
from app.schemas.lubricant import LubricantCreate, LubricantOut, LubricantUpdate, PriceHistoryCreate, PurchaseCreate
from app.services.lubricant_service import LubricantService

router = APIRouter(
    prefix="/lubricants", tags=["lubricants"], dependencies=[Depends(get_current_active_user)]
)


@router.post("", response_model=LubricantOut, status_code=status.HTTP_201_CREATED)
async def create_lubricant(
    body: LubricantCreate,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_manager_or_admin),
) -> LubricantOut:
    service = LubricantService(session)
    product = await service.create_product(body, current_user)
    return LubricantOut.model_validate(product)


@router.get("", response_model=list[LubricantOut])
async def list_lubricants(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
) -> list[LubricantOut]:
    service = LubricantService(session)
    products = await service.list_products(offset=offset, limit=limit)
    return [LubricantOut.model_validate(p) for p in products]


@router.get("/{product_id}", response_model=LubricantOut)
async def get_lubricant(product_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> LubricantOut:
    service = LubricantService(session)
    product = await service.get_product(product_id)
    return LubricantOut.model_validate(product)


@router.patch("/{product_id}", response_model=LubricantOut)
async def update_lubricant(
    product_id: uuid.UUID,
    body: LubricantUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_manager_or_admin),
) -> LubricantOut:
    service = LubricantService(session)
    product = await service.update_product(product_id, body, current_user)
    return LubricantOut.model_validate(product)


@router.post("/{product_id}/price-history", response_model=LubricantOut)
async def add_price_revision(
    product_id: uuid.UUID,
    body: PriceHistoryCreate,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_manager_or_admin),
) -> LubricantOut:
    service = LubricantService(session)
    product = await service.add_price_revision(product_id, body, current_user)
    return LubricantOut.model_validate(product)


@router.post("/{product_id}/purchases", response_model=LubricantOut)
async def add_purchase(
    product_id: uuid.UUID,
    body: PurchaseCreate,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_manager_or_admin),
) -> LubricantOut:
    service = LubricantService(session)
    product = await service.add_purchase(product_id, body, current_user)
    return LubricantOut.model_validate(product)


@router.delete(
    "/{product_id}", response_model=Message, dependencies=[Depends(require_manager_or_admin)]
)
async def delete_lubricant(product_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> Message:
    service = LubricantService(session)
    await service.delete_product(product_id)
    return Message(detail="Lubricant product deleted.")

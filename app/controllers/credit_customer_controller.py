import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db_session, require_manager_or_admin
from app.models.user import User
from app.schemas.credit_customer import (
    CreditCustomerCreate,
    CreditCustomerOut,
    CreditCustomerUpdate,
    CreditLedgerEntryBillUpdate,
    CreditLedgerEntryCreate,
)
from app.services.credit_customer_service import CreditCustomerService

router = APIRouter(prefix="/credit-customers", tags=["credit-customers"], dependencies=[Depends(get_current_active_user)])


@router.get("", response_model=list[CreditCustomerOut])
async def list_credit_customers(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=1000),
    session: AsyncSession = Depends(get_db_session),
) -> list[CreditCustomerOut]:
    service = CreditCustomerService(session)
    customers = await service.list_all(offset=offset, limit=limit)
    return [CreditCustomerOut.model_validate(c) for c in customers]


@router.post("", response_model=CreditCustomerOut, status_code=status.HTTP_201_CREATED)
async def create_credit_customer(
    body: CreditCustomerCreate,
    current_user: User = Depends(require_manager_or_admin),
    session: AsyncSession = Depends(get_db_session),
) -> CreditCustomerOut:
    service = CreditCustomerService(session)
    customer = await service.create(body, current_user)
    return CreditCustomerOut.model_validate(customer)


@router.get("/{customer_id}", response_model=CreditCustomerOut)
async def get_credit_customer(
    customer_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)
) -> CreditCustomerOut:
    service = CreditCustomerService(session)
    customer = await service.get(customer_id)
    return CreditCustomerOut.model_validate(customer)


@router.patch("/{customer_id}", response_model=CreditCustomerOut)
async def update_credit_customer(
    customer_id: uuid.UUID,
    body: CreditCustomerUpdate,
    current_user: User = Depends(require_manager_or_admin),
    session: AsyncSession = Depends(get_db_session),
) -> CreditCustomerOut:
    service = CreditCustomerService(session)
    customer = await service.update(customer_id, body, current_user)
    return CreditCustomerOut.model_validate(customer)


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credit_customer(
    customer_id: uuid.UUID,
    current_user: User = Depends(require_manager_or_admin),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    service = CreditCustomerService(session)
    await service.delete(customer_id)


@router.post("/{customer_id}/ledger", response_model=CreditCustomerOut, status_code=status.HTTP_201_CREATED)
async def add_ledger_entry(
    customer_id: uuid.UUID,
    body: CreditLedgerEntryCreate,
    current_user: User = Depends(require_manager_or_admin),
    session: AsyncSession = Depends(get_db_session),
) -> CreditCustomerOut:
    service = CreditCustomerService(session)
    customer = await service.add_ledger_entry(customer_id, body, current_user)
    return CreditCustomerOut.model_validate(customer)


@router.patch("/{customer_id}/ledger/{entry_id}/bill", response_model=CreditCustomerOut)
async def update_ledger_entry_bill(
    customer_id: uuid.UUID,
    entry_id: uuid.UUID,
    body: CreditLedgerEntryBillUpdate,
    current_user: User = Depends(require_manager_or_admin),
    session: AsyncSession = Depends(get_db_session),
) -> CreditCustomerOut:
    service = CreditCustomerService(session)
    customer = await service.update_ledger_entry_bill(customer_id, entry_id, body, current_user)
    return CreditCustomerOut.model_validate(customer)


@router.delete(
    "/{customer_id}/ledger/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_manager_or_admin)],
)
async def delete_ledger_entry(
    customer_id: uuid.UUID,
    entry_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    service = CreditCustomerService(session)
    await service.delete_ledger_entry(customer_id, entry_id)

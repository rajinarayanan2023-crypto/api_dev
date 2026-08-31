import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db_session, require_manager_or_admin
from app.models.user import User
from app.schemas.common import Message
from app.schemas.expense import ExpenseDayCreate, ExpenseDayOut, ExpenseDayUpdate
from app.services.expense_service import ExpenseService

router = APIRouter(prefix="/expenses", tags=["expenses"], dependencies=[Depends(get_current_active_user)])


@router.post("", response_model=ExpenseDayOut, status_code=status.HTTP_201_CREATED)
async def create_expense_day(
    body: ExpenseDayCreate,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_manager_or_admin),
) -> ExpenseDayOut:
    service = ExpenseService(session)
    day = await service.create_expense_day(body, current_user)
    return ExpenseDayOut.model_validate(day)


@router.get("", response_model=list[ExpenseDayOut])
async def list_expense_days(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
) -> list[ExpenseDayOut]:
    service = ExpenseService(session)
    days = await service.list_expense_days(offset=offset, limit=limit)
    return [ExpenseDayOut.model_validate(d) for d in days]


@router.get("/{expense_day_id}", response_model=ExpenseDayOut)
async def get_expense_day(expense_day_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> ExpenseDayOut:
    service = ExpenseService(session)
    day = await service.get_expense_day(expense_day_id)
    return ExpenseDayOut.model_validate(day)


@router.patch("/{expense_day_id}", response_model=ExpenseDayOut)
async def update_expense_day(
    expense_day_id: uuid.UUID,
    body: ExpenseDayUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_manager_or_admin),
) -> ExpenseDayOut:
    service = ExpenseService(session)
    day = await service.update_expense_day(expense_day_id, body, current_user)
    return ExpenseDayOut.model_validate(day)


@router.delete(
    "/{expense_day_id}", response_model=Message, dependencies=[Depends(require_manager_or_admin)]
)
async def delete_expense_day(expense_day_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> Message:
    service = ExpenseService(session)
    await service.delete_expense_day(expense_day_id)
    return Message(detail="Expense record deleted.")

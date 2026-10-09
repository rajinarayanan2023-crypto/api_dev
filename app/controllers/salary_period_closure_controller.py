from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db_session, require_admin, require_manager_or_admin
from app.models.user import User
from app.schemas.salary_period_closure import (
    SalaryPeriodActionRequest,
    SalaryPeriodCloseRequest,
    SalaryPeriodClosureOut,
)
from app.services.salary_period_closure_service import SalaryPeriodClosureService

router = APIRouter(
    prefix="/salary-period-closures", tags=["salary-period-closures"], dependencies=[Depends(get_current_active_user)]
)


@router.get("", response_model=list[SalaryPeriodClosureOut])
async def list_salary_period_closures(session: AsyncSession = Depends(get_db_session)) -> list[SalaryPeriodClosureOut]:
    service = SalaryPeriodClosureService(session)
    closures = await service.list_all()
    return [SalaryPeriodClosureOut.model_validate(c) for c in closures]


@router.post("", response_model=SalaryPeriodClosureOut, status_code=status.HTTP_201_CREATED)
async def close_salary_period(
    body: SalaryPeriodCloseRequest,
    current_user: User = Depends(require_manager_or_admin),
    session: AsyncSession = Depends(get_db_session),
) -> SalaryPeriodClosureOut:
    service = SalaryPeriodClosureService(session)
    closure = await service.close_period(body.period_year, body.period_month, current_user, body.note)
    return SalaryPeriodClosureOut.model_validate(closure)


# Admin-only, unlike every other salary action — reopening un-does a
# supposedly-final state, which standard payroll products (Tally, QuickBooks)
# treat as more sensitive than closing it in the first place.
@router.post("/{period_year}/{period_month}/reopen", response_model=SalaryPeriodClosureOut)
async def reopen_salary_period(
    body: SalaryPeriodActionRequest,
    period_year: int = Path(ge=2000, le=2100),
    period_month: int = Path(ge=1, le=12),
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> SalaryPeriodClosureOut:
    service = SalaryPeriodClosureService(session)
    closure = await service.reopen_period(period_year, period_month, current_user, body.note)
    return SalaryPeriodClosureOut.model_validate(closure)

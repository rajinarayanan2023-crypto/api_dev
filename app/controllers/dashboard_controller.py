from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db_session
from app.schemas.dashboard import DashboardSummaryOut
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(get_current_active_user)])


@router.get("/summary", response_model=DashboardSummaryOut)
async def get_summary(
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM"),
    session: AsyncSession = Depends(get_db_session),
) -> DashboardSummaryOut:
    service = DashboardService(session)
    summary = await service.get_summary(month)
    return DashboardSummaryOut.model_validate(summary)

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db_session, require_manager_or_admin
from app.models.user import User
from app.schemas.attendance import AttendanceCreate, AttendanceOut, AttendanceUpdate
from app.schemas.common import Message
from app.services.attendance_service import AttendanceService

router = APIRouter(
    prefix="/attendance", tags=["attendance"], dependencies=[Depends(get_current_active_user)]
)


@router.post("", response_model=AttendanceOut, status_code=status.HTTP_201_CREATED)
async def mark_attendance(
    body: AttendanceCreate,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_manager_or_admin),
) -> AttendanceOut:
    service = AttendanceService(session)
    record = await service.mark_attendance(body, current_user)
    return AttendanceOut.model_validate(record)


@router.patch("/{employee_id}/{day}", response_model=AttendanceOut)
async def update_attendance(
    employee_id: uuid.UUID,
    day: date,
    body: AttendanceUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_manager_or_admin),
) -> AttendanceOut:
    service = AttendanceService(session)
    record = await service.update_attendance(employee_id, day, body, current_user)
    return AttendanceOut.model_validate(record)


@router.delete(
    "/{employee_id}/{day}", response_model=Message, dependencies=[Depends(require_manager_or_admin)]
)
async def delete_attendance(
    employee_id: uuid.UUID, day: date, session: AsyncSession = Depends(get_db_session)
) -> Message:
    service = AttendanceService(session)
    await service.delete_attendance(employee_id, day)
    return Message(detail="Attendance record deleted.")


@router.get("", response_model=list[AttendanceOut])
async def list_attendance_for_all(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    session: AsyncSession = Depends(get_db_session),
) -> list[AttendanceOut]:
    service = AttendanceService(session)
    records = await service.list_all_for_month(year, month)
    return [AttendanceOut.model_validate(r) for r in records]


@router.get("/{employee_id}", response_model=list[AttendanceOut])
async def list_attendance_for_month(
    employee_id: uuid.UUID,
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    session: AsyncSession = Depends(get_db_session),
) -> list[AttendanceOut]:
    service = AttendanceService(session)
    records = await service.list_for_month(employee_id, year, month)
    return [AttendanceOut.model_validate(r) for r in records]

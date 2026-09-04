import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db_session, require_manager_or_admin
from app.models.user import User
from app.schemas.common import Message
from app.schemas.employee import (
    EmployeeCreate,
    EmployeeCreditCreate,
    EmployeeCreditUpdate,
    EmployeeOut,
    EmployeeUpdate,
    SalaryHistoryCreate,
)
from app.services.employee_service import EmployeeService

router = APIRouter(
    prefix="/employees", tags=["employees"], dependencies=[Depends(get_current_active_user)]
)


@router.post("", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED)
async def create_employee(
    body: EmployeeCreate,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_manager_or_admin),
) -> EmployeeOut:
    service = EmployeeService(session)
    employee = await service.create_employee(body, current_user)
    return EmployeeOut.model_validate(employee)


@router.get("", response_model=list[EmployeeOut])
async def list_employees(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
) -> list[EmployeeOut]:
    service = EmployeeService(session)
    employees = await service.list_employees(offset=offset, limit=limit)
    return [EmployeeOut.model_validate(e) for e in employees]


@router.get("/{employee_id}", response_model=EmployeeOut)
async def get_employee(employee_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> EmployeeOut:
    service = EmployeeService(session)
    employee = await service.get_employee(employee_id)
    return EmployeeOut.model_validate(employee)


@router.patch("/{employee_id}", response_model=EmployeeOut)
async def update_employee(
    employee_id: uuid.UUID,
    body: EmployeeUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_manager_or_admin),
) -> EmployeeOut:
    service = EmployeeService(session)
    employee = await service.update_employee(employee_id, body, current_user)
    return EmployeeOut.model_validate(employee)


@router.post("/{employee_id}/salary-history", response_model=EmployeeOut)
async def add_salary_revision(
    employee_id: uuid.UUID,
    body: SalaryHistoryCreate,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_manager_or_admin),
) -> EmployeeOut:
    service = EmployeeService(session)
    employee = await service.add_salary_revision(employee_id, body, current_user)
    return EmployeeOut.model_validate(employee)


@router.delete(
    "/{employee_id}", response_model=Message, dependencies=[Depends(require_manager_or_admin)]
)
async def delete_employee(employee_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> Message:
    service = EmployeeService(session)
    await service.delete_employee(employee_id)
    return Message(detail="Employee deleted.")


@router.post("/{employee_id}/credits", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED)
async def add_employee_credit(
    employee_id: uuid.UUID,
    body: EmployeeCreditCreate,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_manager_or_admin),
) -> EmployeeOut:
    service = EmployeeService(session)
    employee = await service.add_credit(employee_id, body, current_user)
    return EmployeeOut.model_validate(employee)


@router.patch("/{employee_id}/credits/{credit_id}", response_model=EmployeeOut)
async def update_employee_credit(
    employee_id: uuid.UUID,
    credit_id: uuid.UUID,
    body: EmployeeCreditUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_manager_or_admin),
) -> EmployeeOut:
    service = EmployeeService(session)
    employee = await service.update_credit(employee_id, credit_id, body, current_user)
    return EmployeeOut.model_validate(employee)


@router.delete(
    "/{employee_id}/credits/{credit_id}",
    response_model=Message,
    dependencies=[Depends(require_manager_or_admin)],
)
async def delete_employee_credit(
    employee_id: uuid.UUID, credit_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)
) -> Message:
    service = EmployeeService(session)
    await service.delete_credit(employee_id, credit_id)
    return Message(detail="Employee credit deleted.")

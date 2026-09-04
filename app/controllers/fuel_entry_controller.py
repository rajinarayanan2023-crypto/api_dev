import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db_session, require_manager_or_admin
from app.models.user import User
from app.schemas.fuel_entry import FuelEntryOut, FuelEntryWrite
from app.services.fuel_entry_service import FuelEntryService

router = APIRouter(prefix="/fuel-entries", tags=["fuel-entries"], dependencies=[Depends(get_current_active_user)])


@router.get("", response_model=list[FuelEntryOut])
async def list_fuel_entries(
    pump_key: str | None = Query(default=None),
    entry_date: date | None = Query(default=None, alias="date"),
    before: date | None = Query(default=None, alias="before", description="Entries strictly before this date — e.g. the most recent prior entry for a pump"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=1000, ge=1, le=2000),
    session: AsyncSession = Depends(get_db_session),
) -> list[FuelEntryOut]:
    service = FuelEntryService(session)
    entries = await service.list_all(offset=offset, limit=limit, pump_key=pump_key, entry_date=entry_date, before=before)
    return [FuelEntryOut(**e) for e in entries]


@router.get("/{entry_id}", response_model=FuelEntryOut)
async def get_fuel_entry(entry_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> FuelEntryOut:
    service = FuelEntryService(session)
    entry = await service.get(entry_id)
    return FuelEntryOut(**entry)


@router.post("", response_model=FuelEntryOut, status_code=status.HTTP_201_CREATED)
async def create_fuel_entry(
    body: FuelEntryWrite,
    current_user: User = Depends(require_manager_or_admin),
    session: AsyncSession = Depends(get_db_session),
) -> FuelEntryOut:
    service = FuelEntryService(session)
    entry = await service.create(body, current_user)
    return FuelEntryOut(**entry)


@router.put("/{entry_id}", response_model=FuelEntryOut)
async def update_fuel_entry(
    entry_id: uuid.UUID,
    body: FuelEntryWrite,
    current_user: User = Depends(require_manager_or_admin),
    session: AsyncSession = Depends(get_db_session),
) -> FuelEntryOut:
    service = FuelEntryService(session)
    entry = await service.update(entry_id, body, current_user)
    return FuelEntryOut(**entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fuel_entry(
    entry_id: uuid.UUID,
    current_user: User = Depends(require_manager_or_admin),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    service = FuelEntryService(session)
    await service.delete(entry_id)

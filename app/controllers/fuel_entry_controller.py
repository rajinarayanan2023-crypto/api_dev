import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db_session, require_manager_or_admin
from app.core.email import send_email
from app.models.user import User
from app.schemas.audit_email_send import AuditEmailSendOut
from app.schemas.fuel_entry import FuelEntryOut, FuelEntryWrite
from app.services.audit_email_send_service import AuditEmailSendService
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


# Registered BEFORE /{entry_id} below on purpose — FastAPI/Starlette tries
# routes in registration order, and /{entry_id} is a catch-all path param
# that would otherwise swallow "/audit-email-log" as if it were an entry id
# (and fail UUID parsing with a 422) since both are GET.
#
# Read-only, same access level as every other GET on this router (any
# authenticated user — see the router-wide dependency above) — the Audit
# modal itself can be opened by anyone with a saved entry for the date,
# only actually SENDING is manager/admin-only (see send_audit_email below).
@router.get("/audit-email-log", response_model=list[AuditEmailSendOut])
async def list_audit_email_sends(
    entry_date: date = Query(..., alias="date"),
    is_shift3: bool = Query(False),
    limit: int = Query(default=3, ge=1, le=20),
    session: AsyncSession = Depends(get_db_session),
) -> list[AuditEmailSendOut]:
    service = AuditEmailSendService(session)
    sends = await service.list_recent(entry_date=entry_date, is_shift3=is_shift3, limit=limit)
    return [AuditEmailSendOut.model_validate(s) for s in sends]


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


# The audit report AuditModal builds (see FuelEntryForm.jsx/AuditModal.jsx)
# is a whole-day, both-pumps report — optionally the separate Shift 3
# variant — never a single Fuel_Entries row, so there's no {entry_id} to
# scope this on the way the other routes above do. The .xlsx itself is
# already fully assembled client-side (buildWorkbookBlob) and sent up as-is
# here purely as the email attachment — this endpoint only ever sends it,
# it never re-derives or re-validates the report's own numbers.
#
# entry_date/is_shift3 identify which Audit modal (day vs Shift 3) this send
# belongs to, purely to record it in Audit_Email_Sends below — send_email
# itself never used them, so adding them can't change anything about how
# the email itself goes out. A send that raises (the provider call fails)
# never reaches the record() call, so Audit_Email_Sends only ever holds
# confirmed sends.
@router.post("/send-audit-email", status_code=status.HTTP_204_NO_CONTENT)
async def send_audit_email(
    to_email: str = Form(...),
    subject: str = Form(...),
    body_text: str = Form(...),
    entry_date: date = Form(..., alias="date"),
    is_shift3: bool = Form(False),
    attachment: UploadFile = File(...),
    current_user: User = Depends(require_manager_or_admin),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    attachment_bytes = await attachment.read()
    send_email(
        to=to_email,
        subject=subject,
        body_text=body_text,
        attachment_bytes=attachment_bytes,
        attachment_filename=attachment.filename or "audit-report.xlsx",
    )
    await AuditEmailSendService(session).record(
        entry_date=entry_date, is_shift3=is_shift3, recipient_email=to_email, actor=current_user
    )

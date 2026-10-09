from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, require_admin
from app.schemas.login_attempt import LoginAttemptOut
from app.services.login_attempt_service import LoginAttemptService

# Admin-only — a login/change-password failure log (including who was
# locked out and why) is exactly the kind of thing a manager account
# shouldn't be able to browse for every other user.
router = APIRouter(prefix="/login-attempts", tags=["login-attempts"], dependencies=[Depends(require_admin)])


@router.get("", response_model=list[LoginAttemptOut])
async def list_login_attempts(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=500),
    identifier: str | None = Query(default=None),
    success: bool | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
) -> list[LoginAttemptOut]:
    service = LoginAttemptService(session)
    attempts = await service.list_attempts(
        offset=offset, limit=limit, identifier=identifier, success=success, date_from=date_from, date_to=date_to
    )
    return [LoginAttemptOut.model_validate(a) for a in attempts]

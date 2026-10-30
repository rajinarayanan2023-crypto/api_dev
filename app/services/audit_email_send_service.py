from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_email_send import AuditEmailSend
from app.models.user import User
from app.repositories.audit_email_send_repository import AuditEmailSendRepository
from app.services.audit import attach_actor_names


class AuditEmailSendService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.sends = AuditEmailSendRepository(session)

    # Called only after the SMTP send itself has already succeeded (see
    # fuel_entry_controller.send_audit_email) — a failed send never reaches
    # here, so this table only ever holds confirmed sends. No explicit
    # commit: the endpoint returns normally right after, and get_db's own
    # commit-on-success (app/core/database.py) covers it the same way every
    # other write-then-succeed endpoint in this app already relies on.
    async def record(self, *, entry_date: date, is_shift3: bool, recipient_email: str, actor: User) -> AuditEmailSend:
        return await self.sends.create(
            AuditEmailSend(
                date=entry_date,
                is_shift3=is_shift3,
                recipient_email=recipient_email,
                created_by=actor.id,
                updated_by=actor.id,
            )
        )

    async def list_recent(self, *, entry_date: date, is_shift3: bool, limit: int = 3) -> list[AuditEmailSend]:
        sends = await self.sends.list_recent(entry_date=entry_date, is_shift3=is_shift3, limit=limit)
        await attach_actor_names(self.session, sends)
        return sends

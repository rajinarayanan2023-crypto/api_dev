from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_email_send import AuditEmailSend
from app.repositories.base import BaseRepository


class AuditEmailSendRepository(BaseRepository[AuditEmailSend]):
    def __init__(self, session: AsyncSession):
        super().__init__(AuditEmailSend, session)

    async def list_recent(self, *, entry_date: date, is_shift3: bool, limit: int = 3) -> list[AuditEmailSend]:
        query = (
            select(AuditEmailSend)
            .where(AuditEmailSend.date == entry_date, AuditEmailSend.is_shift3 == is_shift3)
            .order_by(AuditEmailSend.sent_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

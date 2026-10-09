from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.login_attempt import LoginAttempt
from app.repositories.base import BaseRepository


class LoginAttemptRepository(BaseRepository[LoginAttempt]):
    def __init__(self, session: AsyncSession):
        super().__init__(LoginAttempt, session)

    async def count_recent_failures(self, identifier: str, action: str, since: datetime) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(LoginAttempt)
            .where(
                LoginAttempt.identifier == identifier,
                LoginAttempt.action == action,
                LoginAttempt.success.is_(False),
                LoginAttempt.created_at >= since,
            )
        )
        return result.scalar_one()

    async def list_recent(
        self,
        offset: int = 0,
        limit: int = 100,
        *,
        identifier: str | None = None,
        success: bool | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[LoginAttempt]:
        query = select(LoginAttempt).order_by(LoginAttempt.created_at.desc())
        if identifier:
            # Same substring match the Login Attempts screen's own search
            # box offers — exact-match would be useless for "find every
            # attempt against this account" when the identifier was mistyped
            # slightly differently across attempts.
            query = query.where(LoginAttempt.identifier.ilike(f"%{identifier}%"))
        if success is not None:
            query = query.where(LoginAttempt.success.is_(success))
        if date_from is not None:
            query = query.where(LoginAttempt.created_at >= date_from)
        if date_to is not None:
            query = query.where(LoginAttempt.created_at <= date_to)
        query = query.offset(offset).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

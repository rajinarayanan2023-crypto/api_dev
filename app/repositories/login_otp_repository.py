import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.login_otp import LoginOtp
from app.repositories.base import BaseRepository


class LoginOtpRepository(BaseRepository[LoginOtp]):
    def __init__(self, session: AsyncSession):
        super().__init__(LoginOtp, session)

    async def get_active_for_user(self, user_id: uuid.UUID) -> LoginOtp | None:
        """The most recent not-yet-consumed, not-yet-expired OTP for this
        user — invalidate_for_user() below keeps this to at most one row per
        user, so "most recent" is really just "the only one"."""
        result = await self.session.execute(
            select(LoginOtp)
            .where(
                LoginOtp.user_id == user_id,
                LoginOtp.consumed.is_(False),
                LoginOtp.expires_at > datetime.now(timezone.utc),
            )
            .order_by(LoginOtp.created_at.desc())
        )
        return result.scalars().first()

    async def invalidate_for_user(self, user_id: uuid.UUID) -> None:
        """Deletes any existing OTP rows for this user before issuing a new
        one, so an older leaked/guessed code (or a stale one from an
        abandoned login attempt) can never still be valid alongside it."""
        await self.session.execute(delete(LoginOtp).where(LoginOtp.user_id == user_id))

from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedError
from app.core.security import TokenType, create_access_token, create_refresh_token, decode_token, hash_token
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import TokenResponse

settings = get_settings()


class AuthService:
    """Password check + OTP issuance/verification now live in
    auth_controller (see /auth/login, /auth/verify-otp) — they only touch
    app.core.otp_store plus UserRepository, so there was nothing left here
    to route through a service. This class still owns token issuance and
    the refresh/logout session lifecycle, which every one of those endpoints
    and the OTP ones share.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.users = UserRepository(session)
        self.refresh_tokens = RefreshTokenRepository(session)

    async def issue_tokens(self, user: User) -> TokenResponse:
        access_token = create_access_token(subject=str(user.id), role=user.role)
        refresh_token, _jti, expires_at = create_refresh_token(subject=str(user.id))

        await self.refresh_tokens.create(
            RefreshToken(user_id=user.id, token_hash=hash_token(refresh_token), expires_at=expires_at)
        )
        return TokenResponse(access_token=access_token, refresh_token=refresh_token)

    async def refresh(self, refresh_token: str) -> TokenResponse:
        invalid = UnauthorizedError("Invalid or expired refresh token.")
        try:
            payload = decode_token(refresh_token)
        except jwt.PyJWTError:
            raise invalid

        if payload.get("type") != TokenType.REFRESH.value:
            raise invalid

        stored = await self.refresh_tokens.get_by_token_hash(hash_token(refresh_token))
        if stored is None or stored.revoked or stored.expires_at < datetime.now(timezone.utc):
            raise invalid

        # Auto sign-out after N minutes of inactivity: every successful
        # refresh rotates in a brand new row (see issue_tokens below), so the
        # current token's created_at IS the timestamp of the last login or
        # last refresh — i.e. the last time this session was actually used.
        # A session idle longer than that is force-expired here even though
        # its absolute expires_at (refresh_token_expire_days) hasn't been
        # reached yet.
        idle_cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.idle_timeout_minutes)
        if stored.created_at < idle_cutoff:
            stored.revoked = True
            await self.session.flush()
            raise UnauthorizedError("Session expired due to inactivity. Please sign in again.")

        user = await self.users.get(stored.user_id)
        if user is None or not user.active:
            raise invalid

        # Rotate: the presented refresh token is single-use. Revoking it here
        # means a stolen-but-already-used token can't be replayed.
        stored.revoked = True
        await self.session.flush()

        return await self.issue_tokens(user)

    async def logout(self, refresh_token: str) -> None:
        try:
            payload = decode_token(refresh_token)
        except jwt.PyJWTError:
            return
        if payload.get("type") != TokenType.REFRESH.value:
            return
        stored = await self.refresh_tokens.get_by_token_hash(hash_token(refresh_token))
        if stored is not None:
            stored.revoked = True
            await self.session.flush()

    async def logout_all_sessions(self, user_id) -> None:
        await self.refresh_tokens.revoke_all_for_user(user_id)

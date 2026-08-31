import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    TokenType,
    create_access_token,
    create_otp_pending_token,
    create_refresh_token,
    decode_token,
    hash_token,
    verify_password,
)
from app.core.sms import get_sms_provider
from app.models.login_otp import LoginOtp
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.repositories.login_otp_repository import LoginOtpRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import OtpPendingResponse, TokenResponse

settings = get_settings()


def _generate_otp_code() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(settings.otp_length))


class AuthService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.users = UserRepository(session)
        self.refresh_tokens = RefreshTokenRepository(session)
        self.login_otps = LoginOtpRepository(session)

    async def authenticate(self, identifier: str, password: str) -> User:
        user = await self.users.get_by_identifier(identifier)

        # Deliberately identical error for "no such user" and "wrong password"
        # so login responses never confirm whether an account is registered.
        invalid_credentials = UnauthorizedError("Incorrect email/name or password.")

        if user is None:
            # Still runs a hash comparison so response timing doesn't leak
            # whether the account exists.
            verify_password(password, DUMMY_PASSWORD_HASH)
            raise invalid_credentials

        if not user.active:
            raise ForbiddenError("This account has been deactivated.")

        if not verify_password(password, user.password_hash):
            raise invalid_credentials

        # last_login_at is set once the OTP step also succeeds (see
        # verify_otp_login) — a password-only pass isn't a completed login.
        return user

    async def start_otp_login(self, user: User) -> OtpPendingResponse:
        """Password check passed — generate a code, store its hash, "send"
        it (see app/core/sms.py — no real provider is configured yet, so
        this only logs it server-side), and hand back a short-lived token
        the client must present alongside the code to /auth/verify-otp.
        """
        code = _generate_otp_code()
        await self.login_otps.invalidate_for_user(user.id)
        await self.login_otps.create(
            LoginOtp(
                user_id=user.id,
                code_hash=hash_token(code),
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.otp_expire_minutes),
            )
        )
        await get_sms_provider().send(
            user.phone, f"Your {settings.app_name} login code is {code}. It expires in {settings.otp_expire_minutes} minutes."
        )
        return OtpPendingResponse(
            otp_token=create_otp_pending_token(subject=str(user.id)),
            expires_in_seconds=settings.otp_expire_minutes * 60,
        )

    async def resend_otp(self, otp_token: str) -> OtpPendingResponse:
        user = await self._user_from_otp_token(otp_token)
        return await self.start_otp_login(user)

    async def login_without_otp(self, user: User) -> TokenResponse:
        """Temporary bypass for settings.otp_enabled=False — mirrors what a
        plain password login did before the OTP step existed. Doesn't touch
        start_otp_login/verify_otp_login/resend_otp at all, so flipping
        otp_enabled back to True restores the OTP flow with no code changes.
        """
        user.last_login_at = datetime.now(timezone.utc)
        await self.session.flush()
        return await self.issue_tokens(user)

    async def verify_otp_login(self, otp_token: str, code: str) -> TokenResponse:
        user = await self._user_from_otp_token(otp_token)

        otp = await self.login_otps.get_active_for_user(user.id)
        if otp is None:
            raise UnauthorizedError("This code has expired. Please sign in again.")

        if otp.attempts >= settings.otp_max_attempts:
            otp.consumed = True
            await self.session.flush()
            raise UnauthorizedError("Too many incorrect attempts. Please sign in again.")

        if hash_token(code) != otp.code_hash:
            otp.attempts += 1
            await self.session.flush()
            raise UnauthorizedError("Incorrect code. Please try again.")

        otp.consumed = True
        user.last_login_at = datetime.now(timezone.utc)
        await self.session.flush()

        return await self.issue_tokens(user)

    async def _user_from_otp_token(self, otp_token: str) -> User:
        invalid = UnauthorizedError("This login session has expired. Please sign in again.")
        try:
            payload = decode_token(otp_token)
        except jwt.PyJWTError:
            raise invalid

        if payload.get("type") != TokenType.OTP_PENDING.value:
            raise invalid

        user_id = payload.get("sub")
        if user_id is None:
            raise invalid

        user = await self.users.get(uuid.UUID(user_id))
        if user is None or not user.active:
            raise invalid

        return user

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

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db_session
from app.core.config import get_settings
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.otp_store import generate_otp, verify_otp
from app.core.rate_limit import limiter
from app.core.security import DUMMY_PASSWORD_HASH, verify_password
from app.core.sms import get_sms_provider
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import (
    AuthUser,
    LoginOtpResponse,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    VerifyOtpRequest,
    VerifyOtpResponse,
)
from app.schemas.common import Message
from app.schemas.user import PasswordChange, UserOut
from app.services.auth_service import AuthService
from app.services.user_service import UserService

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginOtpResponse)
@limiter.limit(settings.rate_limit_login)
async def login(
    request: Request,
    credentials: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
) -> LoginOtpResponse:
    # Single query: identifier is matched against email OR name (see
    # UserRepository.get_by_identifier) — no separate lookups.
    user = await UserRepository(session).get_by_identifier(credentials.identifier)

    # Deliberately identical error for "no such user" and "wrong password"
    # so the response never confirms whether an account is registered.
    invalid_credentials = UnauthorizedError("Incorrect email/name or password.")
    if user is None:
        # Still runs a hash comparison so response timing doesn't leak
        # whether the account exists.
        verify_password(credentials.password, DUMMY_PASSWORD_HASH)
        raise invalid_credentials

    # Cheap short-circuit: reject deactivated accounts before paying for a
    # password hash comparison.
    if not user.active:
        raise ForbiddenError("This account has been deactivated.")

    if not verify_password(credentials.password, user.password_hash):
        raise invalid_credentials

    otp = generate_otp(str(user.id))
    await get_sms_provider().send(
        user.phone, f"Your {settings.app_name} login code is {otp}. It expires in 5 minutes."
    )
    return LoginOtpResponse(message="OTP sent.", user_id=str(user.id))


@router.post("/verify-otp", response_model=VerifyOtpResponse)
@limiter.limit(settings.rate_limit_login)
async def verify_otp_route(
    request: Request,
    body: VerifyOtpRequest,
    session: AsyncSession = Depends(get_db_session),
) -> VerifyOtpResponse:
    ok, message = verify_otp(body.user_id, body.otp)
    if not ok:
        raise UnauthorizedError(message)

    try:
        user_id = uuid.UUID(body.user_id)
    except ValueError:
        raise UnauthorizedError("This account is no longer available.")

    user = await UserRepository(session).get(user_id)
    if user is None or not user.active:
        raise UnauthorizedError("This account is no longer available.")

    # Single DB write for the OTP step itself; issue_tokens below adds the
    # one further write it's always made (persisting the new refresh token,
    # needed for /auth/refresh and /auth/logout to keep working).
    user.last_login_at = datetime.now(timezone.utc)
    await session.flush()

    tokens = await AuthService(session).issue_tokens(user)
    return VerifyOtpResponse(
        **tokens.model_dump(),
        user=AuthUser(id=str(user.id), name=user.name, email=user.email, role=user.role),
    )


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit(settings.rate_limit_login)
async def refresh(
    request: Request,
    body: RefreshRequest,
    session: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    service = AuthService(session)
    return await service.refresh(body.refresh_token)


@router.post("/logout", response_model=Message)
async def logout(
    body: RefreshRequest,
    session: AsyncSession = Depends(get_db_session),
) -> Message:
    service = AuthService(session)
    await service.logout(body.refresh_token)
    return Message(detail="Logged out.")


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_active_user)) -> User:
    return current_user


@router.post("/change-password", response_model=Message)
async def change_password(
    body: PasswordChange,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> Message:
    service = UserService(session)
    await service.change_password(current_user, body)
    return Message(detail="Password changed. Please log in again.")

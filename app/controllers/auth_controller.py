from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db_session
from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    OtpPendingResponse,
    RefreshRequest,
    ResendOtpRequest,
    TokenResponse,
    VerifyOtpRequest,
)
from app.schemas.common import Message
from app.schemas.user import PasswordChange, UserOut
from app.services.auth_service import AuthService
from app.services.user_service import UserService

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=OtpPendingResponse | TokenResponse)
@limiter.limit(settings.rate_limit_login)
async def login(
    request: Request,
    credentials: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
) -> OtpPendingResponse | TokenResponse:
    service = AuthService(session)
    user = await service.authenticate(credentials.identifier, credentials.password)
    if not settings.otp_enabled:
        return await service.login_without_otp(user)
    return await service.start_otp_login(user)


@router.post("/verify-otp", response_model=TokenResponse)
@limiter.limit(settings.rate_limit_login)
async def verify_otp(
    request: Request,
    body: VerifyOtpRequest,
    session: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    service = AuthService(session)
    return await service.verify_otp_login(body.otp_token, body.code)


@router.post("/resend-otp", response_model=OtpPendingResponse)
@limiter.limit(settings.rate_limit_login)
async def resend_otp(
    request: Request,
    body: ResendOtpRequest,
    session: AsyncSession = Depends(get_db_session),
) -> OtpPendingResponse:
    service = AuthService(session)
    return await service.resend_otp(body.otp_token)


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

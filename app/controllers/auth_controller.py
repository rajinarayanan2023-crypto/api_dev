import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db_session
from app.core.config import get_settings
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.email import send_email
from app.core.otp_store import generate_otp, otp_expiry_phrase, verify_otp
from app.core.rate_limit import limiter
from app.core.security import DUMMY_PASSWORD_HASH, verify_password
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


def _otp_email_text(otp: str, expiry_phrase: str) -> str:
    """Plain-text fallback for mail clients that don't render the HTML
    alternative below — same wording, no styling.
    """
    return (
        "Hello,\n\n"
        f"Your One-Time Password (OTP) for logging in to GM Agency App is:\n\n"
        f"{otp}\n\n"
        f"This OTP is valid for {expiry_phrase}. Please do not share this OTP with anyone.\n\n"
        "If you did not request this OTP, you can safely ignore this email.\n\n"
        "Regards,\n"
        "GM Agency Software Team"
    )


def _otp_email_html(otp: str, expiry_phrase: str) -> str:
    """Colorful HTML template for the login OTP email — gold/navy to match
    the app's own brand palette (see ui/tailwind.config.js's brand.* scale).
    Table-based layout with inline styles only, since that's what actually
    renders consistently across Gmail/Outlook/etc.
    """
    return f"""\
<div style="background:#f1f5f9;padding:32px 16px;font-family:'Segoe UI',Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td align="center">
        <table role="presentation" width="480" cellpadding="0" cellspacing="0"
               style="max-width:480px;width:100%;background:#ffffff;border-radius:14px;overflow:hidden;box-shadow:0 8px 30px rgba(15,23,42,0.15);">
          <tr>
            <td style="background:linear-gradient(135deg,#f5a800,#c9911c 60%,#8a5c10);padding:28px 32px;text-align:center;">
              <div style="font-size:22px;font-weight:700;color:#ffffff;letter-spacing:1px;">GM AGENCY</div>
              <div style="font-size:13px;color:#fde8b8;margin-top:4px;">Fuel Station Management</div>
            </td>
          </tr>
          <tr>
            <td style="padding:32px;">
              <p style="margin:0 0 16px;font-size:15px;color:#334155;">Hello,</p>
              <p style="margin:0 0 22px;font-size:15px;color:#334155;line-height:1.6;">
                Your One-Time Password (OTP) for logging in to <strong>GM Agency App</strong> is:
              </p>
              <div style="text-align:center;margin:24px 0;">
                <span style="display:inline-block;background:linear-gradient(135deg,#fff4de,#ffe6ad);border:1.5px solid #f0b429;color:#8a5c10;font-size:32px;font-weight:800;letter-spacing:8px;padding:14px 28px;border-radius:12px;">
                  {otp}
                </span>
              </div>
              <p style="margin:0 0 8px;font-size:13.5px;color:#64748b;text-align:center;">
                This OTP is valid for <strong style="color:#c9911c;">{expiry_phrase}</strong>.
              </p>
              <p style="margin:0 0 20px;font-size:13px;color:#e11d48;text-align:center;font-weight:600;">
                Please do not share this OTP with anyone.
              </p>
              <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0;">
              <p style="margin:0;font-size:12.5px;color:#94a3b8;">
                If you did not request this OTP, you can safely ignore this email.
              </p>
            </td>
          </tr>
          <tr>
            <td style="background:#0f172a;padding:18px 32px;text-align:center;">
              <p style="margin:0;font-size:12px;color:#94a3b8;">Regards,</p>
              <p style="margin:2px 0 0;font-size:13px;color:#f5a800;font-weight:700;">GM Agency Software Team</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</div>
"""


# TESTING BYPASS — response_model temporarily changed from LoginOtpResponse
# to VerifyOtpResponse while the OTP email step below is disabled (Railway
# blocks outbound SMTP ports in production). To revert: change this back to
# response_model=LoginOtpResponse and restore the `-> LoginOtpResponse`
# return type below.
@router.post("/login", response_model=VerifyOtpResponse)
@limiter.limit(settings.rate_limit_login)
async def login(
    request: Request,
    credentials: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
) -> VerifyOtpResponse:
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

    # ------------------------------------------------------------------
    # TESTING BYPASS — OTP-by-email temporarily disabled (Railway blocks
    # outbound SMTP ports, so send_email() throws OSError in production).
    # Issuing real tokens straight away instead of emailing an OTP, so a
    # correct password alone logs the user in.
    #
    # To revert: delete this block, uncomment the ORIGINAL block below,
    # and restore response_model=LoginOtpResponse / -> LoginOtpResponse
    # above.
    # ------------------------------------------------------------------
    user.last_login_at = datetime.now(timezone.utc)
    await session.flush()
    tokens = await AuthService(session).issue_tokens(user)
    return VerifyOtpResponse(
        **tokens.model_dump(),
        user=AuthUser(id=str(user.id), name=user.name, email=user.email, role=user.role),
    )

    # ---------------- ORIGINAL (OTP-via-email) — commented out for testing ----------------
    # otp = generate_otp(str(user.id))
    # # OTP now goes to the user's registered email, not SMS — a real SMS send
    # # costs money per login (see app/core/sms.py/Fast2SMSProvider, still used
    # # by the Offers module), while email is free via the existing SMTP setup.
    # # This is a login-only change: Offers' SMS channel is untouched. from_name
    # # overrides the sender display name just for this email — audit report
    # # emails keep the default settings.smtp_from_name.
    # expiry = otp_expiry_phrase()
    # send_email(
    #     user.email,
    #     "Welcome to the GM Agency App - Your OTP code",
    #     _otp_email_text(otp, expiry),
    #     html_body=_otp_email_html(otp, expiry),
    #     from_name="GM Agency App OTP",
    # )
    # return LoginOtpResponse(message="OTP sent.", user_id=str(user.id))


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

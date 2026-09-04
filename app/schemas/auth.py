from pydantic import BaseModel, Field

from app.models.user import UserRole


class LoginRequest(BaseModel):
    # Accepts either the account's email or its display name — looked up
    # case-insensitively against both columns (see UserRepository.get_by_identifier).
    identifier: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class LoginOtpResponse(BaseModel):
    """Returned once the password check passes — the OTP itself lives only
    in app.core.otp_store, keyed by user_id."""

    message: str
    user_id: str


class VerifyOtpRequest(BaseModel):
    user_id: str
    otp: str = Field(min_length=4, max_length=8)


class AuthUser(BaseModel):
    id: str
    name: str
    email: str
    role: UserRole


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class VerifyOtpResponse(TokenResponse):
    user: AuthUser

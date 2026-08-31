from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    # Accepts either the account's email or its display name — looked up
    # case-insensitively against both columns (see UserRepository.get_by_identifier).
    identifier: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class OtpPendingResponse(BaseModel):
    """Returned once the password check passes — the real access/refresh
    tokens aren't issued until the code is verified via /auth/verify-otp."""

    otp_token: str
    expires_in_seconds: int


class VerifyOtpRequest(BaseModel):
    otp_token: str
    code: str = Field(min_length=4, max_length=8)


class ResendOtpRequest(BaseModel):
    otp_token: str

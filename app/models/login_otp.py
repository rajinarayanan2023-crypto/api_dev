import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPkMixin

# Ephemeral auth state, not a business record — same category as
# RefreshToken (see models/refresh_token.py): no AuditMixin, just its own
# short lifecycle (created, consumed or expired). Only the SHA-256 hash of
# the code is ever stored, never the raw value.


class LoginOtp(Base, UUIDPkMixin):
    __tablename__ = "Login_Otps"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Wrong-code attempts against this specific OTP — capped at
    # settings.otp_max_attempts in AuthService, independent of the
    # request-level rate limit on /auth/verify-otp itself.
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

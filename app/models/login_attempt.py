import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPkMixin


class LoginAttempt(Base, UUIDPkMixin):
    """Every login, verify-otp, and change-password attempt — success AND
    failure, including ones rejected outright for already being locked out
    (reason='locked_out') — written here, not just logged to console. Two
    real gaps this closes: there was no durable record of failed logins at
    all, and slowapi's per-IP rate limiting (see core/rate_limit.py) can't
    catch many different IPs each trying a few passwords against the same
    account — LoginAttemptService.check_lockout queries recent rows FROM
    THIS TABLE by identifier, not by IP, to catch exactly that.

    user_id is nullable (and SET NULL on delete) since a failed attempt
    against a nonexistent identifier, or one whose account is later
    deleted, still needs to be recorded — this table's whole point is
    visibility into attempts, including ones that never resolved to a real
    user.
    """

    __tablename__ = "Login_Attempts"
    __table_args__ = (
        CheckConstraint("action IN ('login', 'verify_otp', 'change_password')", name="ck_login_attempts_action"),
        # The lockout check (recent failures for one identifier+action) and
        # the admin screen's own default newest-first listing are the only
        # two query shapes this table ever serves — both indexed directly.
        Index("idx_login_attempts_identifier_action_created", "identifier", "action", "created_at"),
        Index("idx_login_attempts_created", "created_at"),
    )

    # Exactly what was typed/attempted — NOT normalized to the resolved
    # user's canonical email, since a failed attempt may never resolve to a
    # real user at all (see user_id below). Lockout lookups match on this
    # raw value, same as the login endpoint's own identifier lookup.
    identifier: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("Users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # e.g. "wrong_password", "no_such_user", "account_deactivated",
    # "locked_out", "wrong_current_password", "wrong_otp" — None on success.
    reason: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

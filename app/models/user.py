import enum
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuditMixin, Base, UUIDPkMixin


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    STAFF = "staff"


class User(Base, UUIDPkMixin, AuditMixin):
    """No screen creates these today — seeded directly via scripts/create_admin.py.
    created_by is null for that bootstrap admin (no acting user yet) and set
    for every user created afterwards via POST /users.
    """

    __tablename__ = "Users"
    __table_args__ = (CheckConstraint("role IN ('admin', 'manager', 'staff')", name="ck_users_role"),)

    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'staff'"))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    # Where login OTPs are sent (see LoginOtp/AuthService) — nullable since
    # existing accounts predate the OTP feature and have none on file yet.
    phone: Mapped[str | None] = mapped_column(Text)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

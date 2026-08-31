import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.core.database import Base

__all__ = ["Base", "UUIDPkMixin", "AuditMixin"]


class UUIDPkMixin:
    """gen_random_uuid() is native to Postgres 13+ (no pgcrypto/uuid-ossp
    extension needed) — matches every table in the supplied schema, which
    generates ids server-side rather than client-side.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


class AuditMixin:
    """created_at/updated_at are DB-computed (server_default/onupdate); a raw
    SQL UPDATE that bypasses the ORM won't touch updated_at, but every write
    path in this app goes through SQLAlchemy. created_by/updated_by are NOT
    auto-populated here — they depend on who's making the request, so the
    service layer must set them explicitly from the acting user. SET NULL on
    delete so a removed user account doesn't take the audit trail with it.
    """

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), onupdate=text("now()")
    )

    @declared_attr
    def created_by(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(UUID(as_uuid=True), ForeignKey("Users.id", ondelete="SET NULL"))

    @declared_attr
    def updated_by(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(UUID(as_uuid=True), ForeignKey("Users.id", ondelete="SET NULL"))

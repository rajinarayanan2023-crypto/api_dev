from datetime import date as date_, datetime

from sqlalchemy import Boolean, Date, DateTime, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuditMixin, Base, UUIDPkMixin


class AuditEmailSend(Base, UUIDPkMixin, AuditMixin):
    """One row per successful Audit-report email send (see
    fuel_entry_controller.send_audit_email) — the AuditModal has no other
    way to know "was this already emailed today, and to whom" once it's
    closed and reopened, since the send itself was previously a fire-and-
    forget SMTP call with nothing persisted. A failed send (the provider
    call raised) never reaches the point where this gets created — only
    confirmed sends are recorded, matching what "last sent" should mean.

    date + is_shift3 together identify which of the two Audit modals (the
    main day audit, or the separate Shift 3 one — see AuditModal.jsx's
    variantLabel/hasShift3 props) a send belongs to, same two-value scoping
    FuelEntryService already uses elsewhere for the same distinction.
    """

    __tablename__ = "Audit_Email_Sends"
    __table_args__ = (
        # The only query shape this table ever serves: "last N sends for
        # this exact date + audit type", newest first.
        Index("idx_audit_email_sends_date_shift3_sent_at", "date", "is_shift3", "sent_at"),
    )

    date: Mapped[date_] = mapped_column(Date, nullable=False)
    is_shift3: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    recipient_email: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

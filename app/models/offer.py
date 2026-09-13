import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditMixin, Base, UUIDPkMixin


class OfferCustomer(Base, UUIDPkMixin):
    """Standalone recipient list for offers — deliberately not linked, at
    the database level, to Employees, Credit_Customers, OR Offer_Send_Recipients
    (below): a send's recipient rows snapshot the customer's name at send
    time instead of holding a live FK back here, so this table has nothing
    else in the schema referencing it. `active` still exists for
    programmatic use, but the Offers screen itself hard-deletes a removed
    recipient (see OfferCustomerService.delete) rather than deactivating —
    and since nothing references this table, that delete has zero side
    effects anywhere else, past send history included.
    """

    __tablename__ = "offer_customers"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), onupdate=text("now()")
    )


class OfferSend(Base, UUIDPkMixin, AuditMixin):
    """One row per "Send Offer" click — Offer_Send_Recipients (below) records
    one row per selected customer, so "Recently Sent" / the history view
    survives a refresh instead of living in React state.
    """

    __tablename__ = "Offer_Sends"
    __table_args__ = (CheckConstraint("channel IN ('sms', 'whatsapp')", name="ck_offer_sends_channel"),)

    message: Mapped[str] = mapped_column(Text, nullable=False)
    # Both channels are now dispatched server-side — see OfferService.send /
    # core/sms.py — so every recipient gets a real per-channel provider
    # response instead of the old client-side-only wa.me deep link.
    channel: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'sms'"))
    # Which quick-reply template (if any) seeded the message — purely
    # informational, shown in the history view.
    template_used: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    recipients: Mapped[list["OfferSendRecipient"]] = relationship(
        back_populates="offer_send", cascade="all, delete-orphan"
    )


class OfferSendRecipient(Base, UUIDPkMixin):
    """No FK to offer_customers — customer_name is a snapshot taken at send
    time (see OfferService.send), not a live join. This is what makes
    offer_customers a genuinely standalone table: deleting a customer can
    never affect a past send's recipient list, because nothing here points
    back at it.
    """

    __tablename__ = "Offer_Send_Recipients"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'sent', 'failed', 'blocked')", name="ck_offer_send_recipients_status"),
        Index("idx_offer_send_recipients_send", "offer_send_id"),
    )

    offer_send_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Offer_Sends.id", ondelete="CASCADE"), nullable=False
    )
    customer_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    # Raw text from the provider (an error message, or a provider message
    # id on success) — kept simple rather than a JSON column since neither
    # provider here is a real integration yet (see core/sms.py).
    provider_response: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    offer_send: Mapped["OfferSend"] = relationship(back_populates="recipients")

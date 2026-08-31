import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditMixin, Base, UUIDPkMixin


class OfferSend(Base, UUIDPkMixin, AuditMixin):
    """The recipient list is Credit_Customers, reused as-is — this table (and
    Offer_Send_Recipients) only records the send event itself, so "Recently
    Sent" survives a refresh instead of living in React state.
    """

    __tablename__ = "Offer_Sends"

    message: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    recipients: Mapped[list["OfferSendRecipient"]] = relationship(
        back_populates="offer_send", cascade="all, delete-orphan"
    )


class OfferSendRecipient(Base, UUIDPkMixin):
    __tablename__ = "Offer_Send_Recipients"
    __table_args__ = (
        UniqueConstraint("offer_send_id", "customer_id", name="uq_offer_send_recipients_send_customer"),
        Index("idx_offer_send_recipients_send", "offer_send_id"),
        Index("idx_offer_send_recipients_customer", "customer_id"),
    )

    offer_send_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Offer_Sends.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("Credit_Customers.id", ondelete="CASCADE"), nullable=False
    )

    offer_send: Mapped["OfferSend"] = relationship(back_populates="recipients")

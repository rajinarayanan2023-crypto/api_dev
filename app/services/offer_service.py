import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.sms import get_sms_provider, get_whatsapp_provider
from app.models.offer import OfferCustomer, OfferSend, OfferSendRecipient
from app.models.user import User
from app.repositories.offer_repository import OfferSendRepository
from app.schemas.offer import OfferSendCreate
from app.services.audit import attach_actor_names


def _attach_recipient_names(sends: list[OfferSend], names: dict[uuid.UUID, str]) -> None:
    for send in sends:
        for r in send.recipients:
            r.customer_name = names.get(r.offer_customer_id, "Unknown customer")


def _attach_status_counts(sends: list[OfferSend]) -> None:
    for send in sends:
        counts: dict[str, int] = {}
        for r in send.recipients:
            counts[r.status] = counts.get(r.status, 0) + 1
        send.status_counts = counts


class OfferService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.sends = OfferSendRepository(session)

    async def send(self, data: OfferSendCreate, actor: User) -> OfferSend:
        result = await self.session.execute(
            select(OfferCustomer.id, OfferCustomer.name, OfferCustomer.phone).where(
                OfferCustomer.id.in_(data.customer_ids)
            )
        )
        rows = result.all()
        found = {row[0]: (row[1], row[2]) for row in rows}
        missing = set(data.customer_ids) - found.keys()
        if missing:
            raise NotFoundError("One or more selected customers no longer exist.")

        provider = get_sms_provider() if data.channel == "sms" else get_whatsapp_provider()

        send = OfferSend(
            message=data.message,
            channel=data.channel,
            template_used=data.template_used,
            created_by=actor.id,
            updated_by=actor.id,
        )
        recipients = []
        for customer_id in data.customer_ids:
            _, phone = found[customer_id]
            recipient = OfferSendRecipient(offer_customer_id=customer_id)
            if not phone:
                recipient.status = "blocked"
                recipient.provider_response = "No phone number on file."
            else:
                try:
                    await provider.send(phone, data.message)
                    recipient.status = "sent"
                    recipient.sent_at = datetime.now(timezone.utc)
                except Exception as exc:  # noqa: BLE001 — recorded per-recipient, not raised
                    recipient.status = "failed"
                    recipient.provider_response = str(exc)
            recipients.append(recipient)
        send.recipients = recipients
        created = await self.sends.create(send)

        # create() only refreshes the OfferSend row itself, not the
        # recipients relationship (already loaded via the assignment above,
        # but each row needs its DB-assigned id + a fresh session identity) —
        # re-fetch with recipients eagerly loaded so serialization is safe.
        full = await self.sends.get_with_recipients(created.id)
        await attach_actor_names(self.session, [full])
        names = {cid: name for cid, (name, _phone) in found.items()}
        _attach_recipient_names([full], names)
        _attach_status_counts([full])
        return full

    async def list_history(self, offset: int = 0, limit: int = 100) -> list[OfferSend]:
        sends = await self.sends.list_with_recipients(offset=offset, limit=limit)
        await attach_actor_names(self.session, sends)

        ids = {r.offer_customer_id for send in sends for r in send.recipients}
        names: dict[uuid.UUID, str] = {}
        if ids:
            result = await self.session.execute(select(OfferCustomer.id, OfferCustomer.name).where(OfferCustomer.id.in_(ids)))
            names = dict(result.all())
        _attach_recipient_names(sends, names)
        _attach_status_counts(sends)
        return sends

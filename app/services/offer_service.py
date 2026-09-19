from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFoundError
from app.core.sms import get_whatsapp_provider
from app.models.offer import OfferCustomer, OfferSend, OfferSendRecipient
from app.models.user import User
from app.repositories.offer_repository import OfferSendRepository
from app.schemas.offer import OfferSendCreate
from app.services.audit import attach_actor_names
from app.services.station_service import StationService

# The fixed set of approved Meta WhatsApp templates Offers can send —
# submitted via the message_templates API (see git history for the exact
# request), one entry per canned option the UI offers. Keyed by the same id
# Offers.jsx already used for its old client-side-only quick-reply presets,
# so the frontend's existing selector wires straight into this. Each
# template's body has exactly one slot, {{2}}, for whatever offer-specific
# value varies per send (a discount, a litre threshold, a cashback %) —
# {{1}} is always the station name. Confirm APPROVED status in Meta's
# dashboard before relying on these; all four were PENDING as of this commit.
OFFER_TEMPLATES: dict[str, dict[str, str]] = {
    "tamil-bulk-1": {"name": "offer_tamil_bulk_short", "language": "ta", "label": "Tamil · Bulk Offer (Short)"},
    "tamil-bulk-2": {"name": "offer_tamil_bulk_detailed", "language": "ta", "label": "Tamil · Bulk Offer (Detailed)"},
    "english-bulk": {"name": "offer_english_bulk", "language": "en", "label": "English · Bulk Offer"},
    "loyalty-credit": {"name": "offer_loyalty_credit_reminder", "language": "en", "label": "English · Loyalty / Credit Reminder"},
}


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
        template = OFFER_TEMPLATES.get(data.template_used)
        if template is None:
            raise AppError(f"Unknown offer template: {data.template_used!r}")

        # De-duplicated (preserving order) — offer_customers has no unique
        # constraint tying a send to a customer any more (see
        # OfferSendRecipient's docstring), so a request naming the same id
        # twice would otherwise silently create two identical recipient rows.
        customer_ids = list(dict.fromkeys(data.customer_ids))
        result = await self.session.execute(
            select(OfferCustomer.id, OfferCustomer.name, OfferCustomer.phone).where(
                OfferCustomer.id.in_(customer_ids)
            )
        )
        found = {row[0]: (row[1], row[2]) for row in result.all()}
        missing = set(customer_ids) - found.keys()
        if missing:
            raise NotFoundError("One or more selected customers no longer exist.")

        provider = get_whatsapp_provider()
        station = await StationService(self.session).get_station()
        # Not what's actually delivered (that's the template's own approved
        # wording, filled in via send_template below) — just a readable
        # summary for the "Recently Sent" history view/DB row, which still
        # requires some non-empty `message` text.
        preview_message = f"{template['label']} — {data.offer_variable}"

        send = OfferSend(
            message=preview_message,
            # SMS was removed as a channel — every new send is WhatsApp now.
            # Historical rows can still be "sms"; this never rewrites those.
            channel="whatsapp",
            template_used=data.template_used,
            created_by=actor.id,
            updated_by=actor.id,
        )
        recipients = []
        for customer_id in customer_ids:
            name, phone = found[customer_id]
            # Snapshot the name/phone now — this row never looks the customer
            # up again, so it reads the same after the customer is renamed,
            # has its number changed, or is deleted (see OfferSendRecipient's
            # docstring).
            recipient = OfferSendRecipient(customer_name=name, customer_phone=phone)
            if not phone:
                recipient.status = "blocked"
                recipient.provider_response = "No phone number on file."
            else:
                try:
                    # send_text (free-form) can't reach a customer who
                    # hasn't messaged first, within 24h — confirmed via real
                    # testing — so this always goes out as the approved
                    # template. {{1}} station name, {{2}} the one
                    # offer-specific value, matching the order OFFER_TEMPLATES'
                    # own submitted body text references them in.
                    await provider.send_template(
                        phone, template["name"], template["language"], [station.name, data.offer_variable]
                    )
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
        _attach_status_counts([full])
        return full

    async def list_history(self, offset: int = 0, limit: int = 100) -> list[OfferSend]:
        sends = await self.sends.list_with_recipients(offset=offset, limit=limit)
        await attach_actor_names(self.session, sends)
        _attach_status_counts(sends)
        return sends

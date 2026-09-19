import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

# "sms" is a historical value only — no send can produce it any more (see
# OfferService.send, which now always writes "whatsapp"); kept here so
# OfferSendOut can still deserialize/display old rows correctly.
Channel = Literal["sms", "whatsapp"]
RecipientStatus = Literal["pending", "sent", "failed", "blocked"]


class OfferSendCreate(BaseModel):
    customer_ids: list[uuid.UUID] = Field(min_length=1)
    # No more free-typed `message` — WhatsApp only delivers a cold outbound
    # send (no prior message from the customer) via a pre-approved template
    # (confirmed via real testing), and Meta rejects templates that are
    # mostly one big variable, so arbitrary text was never going to work
    # here. template_used now picks one of a fixed set of approved offer
    # templates (see OFFER_TEMPLATES in offer_service.py) instead of
    # seeding a freeform textarea.
    template_used: str = Field(min_length=1)
    # The one offer-specific value each template's body has a slot for
    # (a discount, a litre threshold, a cashback %, ...) — everything else
    # in the message is the template's own fixed, already-approved wording.
    offer_variable: str = Field(min_length=1, max_length=100)


class OfferTemplatePreviewOut(BaseModel):
    # Meta's own review status for this template ("APPROVED", "PENDING",
    # "REJECTED", ...) — surfaced so the UI can warn if someone's about to
    # send a template that isn't actually approved yet.
    status: str
    header_format: str | None = None
    # The real approved body text with {{1}}/{{2}} already substituted —
    # fetched live from Meta (see MetaWhatsAppProvider.get_template_info),
    # never a hand-copied guess that could drift from what's actually live.
    preview_text: str


class OfferSendRecipientOut(ORMModel):
    customer_name: str
    customer_phone: str | None = None
    status: RecipientStatus
    provider_response: str | None = None
    sent_at: datetime | None = None


class OfferSendOut(ORMModel):
    id: uuid.UUID
    message: str
    channel: Channel
    template_used: str | None = None
    sent_at: datetime
    recipients: list[OfferSendRecipientOut] = []
    # Computed in the service layer from the already eager-loaded recipients
    # (no extra query) — the counts the history view's summary chips need,
    # without making the frontend re-derive them from the full list every time.
    status_counts: dict[str, int] = {}
    created_by: uuid.UUID | None = None
    created_by_name: str | None = None

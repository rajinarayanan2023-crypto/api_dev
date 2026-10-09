import logging

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.core.config import get_settings
from app.services.offer_service import OfferService

logger = logging.getLogger("app.whatsapp_webhook")
settings = get_settings()

# Only statuses OfferSendRecipient.status's own CHECK constraint actually
# allows (see models/offer.py) — Meta's statuses API can also report
# "deleted" (one side deleted the message from their own chat) or other
# values outside what this app models as a delivery outcome; anything not
# in this set is logged and left alone rather than attempted (and failing
# the DB write, or silently drifting the schema from what the constraint
# promises).
_RECOGNIZED_STATUSES = {"sent", "delivered", "read", "failed"}

# Deliberately its own router, NOT mounted under anything requiring
# get_current_active_user — Meta's servers call this directly and can't
# authenticate as an app user. The GET verify-token check below is what
# stands in for auth on the one-time subscription handshake; POST deliveries
# after that aren't signed-and-checked yet (see the comment on receive()) —
# a known gap, not an oversight.
router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp-webhook"])


@router.get("")
async def verify(
    hub_mode: str = Query(alias="hub.mode", default=""),
    hub_verify_token: str = Query(alias="hub.verify_token", default=""),
    hub_challenge: str = Query(alias="hub.challenge", default=""),
) -> Response:
    """Meta's one-time subscription handshake: hits this with a token you
    set in its dashboard, expects that exact token echoed back matched
    against ours, and the challenge string echoed back verbatim as plain
    text (not JSON) to prove the endpoint. Anything else must come back as
    a 403 per Meta's own spec, or the subscription is refused.
    """
    if hub_mode == "subscribe" and settings.meta_whatsapp_webhook_verify_token and hub_verify_token == settings.meta_whatsapp_webhook_verify_token:
        return Response(content=hub_challenge, media_type="text/plain")
    logger.warning("WhatsApp webhook verification rejected (mode=%s, token matched=%s)", hub_mode, hub_verify_token == settings.meta_whatsapp_webhook_verify_token)
    return Response(status_code=403)


@router.post("")
async def receive(request: Request, session: AsyncSession = Depends(get_db_session)) -> Response:
    """Real delivery-status events land here asynchronously — sent,
    delivered, read, or failed, keyed by the same message_id MetaWhatsAppProvider
    returns at send time (see core/sms.py). This is what actually answers
    "did it arrive", which a 200 from the send call alone never proves —
    matched back to the specific OfferSendRecipient row via its
    wa_message_id and written there (see OfferService.update_delivery_status),
    so "Recently Sent" on the Offers screen reflects a real delivered/read/
    failed outcome instead of just "sent" (accepted by Meta) forever.

    Always returns 200 — Meta retries (with backoff, eventually disabling
    the webhook) on anything else, and a transient DB hiccup here should
    never look like a delivery failure worth Meta retrying; every per-event
    failure is caught and logged instead of raised.

    Not yet verifying Meta's X-Hub-Signature-256 (HMAC over the raw body
    using the Meta App Secret, which hasn't been provided/configured here)
    — anyone who finds this URL could currently POST a fake status for a
    real wa_message_id and overwrite it. Low risk today (a wrong status
    display, not a wrong send), but add signature verification before
    anything here ever drives real logic (e.g. auto-retrying a failed send).
    """
    try:
        body = await request.json()
    except ValueError:
        logger.warning("WhatsApp webhook received a non-JSON body")
        return Response(status_code=200)

    offers = OfferService(session)

    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for status in value.get("statuses", []):
                message_id = status.get("id")
                delivery_status = status.get("status")
                recipient = status.get("recipient_id")
                errors = status.get("errors")
                if errors:
                    logger.error(
                        "WhatsApp status for message_id=%s to %s: %s — errors=%s",
                        message_id, recipient, delivery_status, errors,
                    )
                else:
                    logger.info(
                        "WhatsApp status for message_id=%s to %s: %s",
                        message_id, recipient, delivery_status,
                    )

                if not message_id or delivery_status not in _RECOGNIZED_STATUSES:
                    continue
                try:
                    error_detail = "; ".join(e.get("title", "") for e in errors) if errors else None
                    matched = await offers.update_delivery_status(message_id, delivery_status, error_detail)
                    if not matched:
                        logger.info("WhatsApp status for message_id=%s matched no known send", message_id)
                except Exception:  # noqa: BLE001 — must never fail this request
                    logger.exception("Failed to record WhatsApp delivery status for message_id=%s", message_id)
            for message in value.get("messages", []):
                # An inbound message FROM the customer (e.g. a reply) — not
                # sent by this app, just logged for visibility. No auto-reply
                # logic exists; nothing here acts on it.
                logger.info("WhatsApp inbound message from %s: %s", message.get("from"), message.get("id"))

    return Response(status_code=200)

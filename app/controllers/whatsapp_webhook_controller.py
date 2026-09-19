import logging

from fastapi import APIRouter, Query, Request, Response

from app.core.config import get_settings

logger = logging.getLogger("app.whatsapp_webhook")
settings = get_settings()

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
async def receive(request: Request) -> Response:
    """Real delivery-status events land here asynchronously — sent,
    delivered, read, or failed, keyed by the same message_id MetaWhatsAppProvider
    logs at send time (see core/sms.py). This is what actually answers "did
    it arrive", which a 200 from the send call alone never proves.

    Always returns 200 — Meta retries (with backoff, eventually disabling
    the webhook) on anything else, and a transient logging hiccup here
    should never look like a delivery failure worth Meta retrying.

    Not yet verifying Meta's X-Hub-Signature-256 (HMAC over the raw body
    using the Meta App Secret, which hasn't been provided/configured here)
    — anyone who finds this URL could currently POST fake events. Low risk
    today (this only logs, writes nothing), but add signature verification
    before this ever drives real logic (e.g. auto-retrying a failed send).
    """
    try:
        body = await request.json()
    except ValueError:
        logger.warning("WhatsApp webhook received a non-JSON body")
        return Response(status_code=200)

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
            for message in value.get("messages", []):
                # An inbound message FROM the customer (e.g. a reply) — not
                # sent by this app, just logged for visibility. No auto-reply
                # logic exists; nothing here acts on it.
                logger.info("WhatsApp inbound message from %s: %s", message.get("from"), message.get("id"))

    return Response(status_code=200)

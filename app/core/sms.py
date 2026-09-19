import logging
import re
from abc import ABC, abstractmethod

import httpx

from app.core.config import get_settings
from app.core.exceptions import AppError

logger = logging.getLogger("app.sms")
settings = get_settings()

# Meta deprecates old Graph API versions roughly every couple of years —
# bump this if it starts returning a deprecation warning/error.
_META_GRAPH_VERSION = "v26.0"
_META_TIMEOUT_SECONDS = 15.0  # documents take a bit longer than plain text (Meta fetches the link server-side)


def _mask(token: str) -> str:
    """Never put a real access token in a log line — first/last 4 chars only."""
    if len(token) <= 8:
        return "***"
    return f"{token[:4]}...{token[-4:]}"


def _to_e164(phone: str) -> str:
    """Meta's docs explicitly recommend a leading '+' and full country code
    on the "to" field — omitting '+' makes Meta prepend the BUSINESS
    number's country code instead of the customer's, which can misdeliver
    the message entirely, not just fail cleanly.

    Every phone number in this app is stored as a bare 10-digit Indian
    mobile number (see Offers.jsx/CreditBills.jsx's `^\\d{10}$` validation) —
    mirrors the same digit-length heuristic already used by
    BrandIcons.jsx's buildWhatsAppLink (which prepends "91" the same way,
    just without the "+", since wa.me links don't want one).
    """
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10:
        digits = f"91{digits}"
    return f"+{digits}"


class WhatsAppSendError(AppError):
    status_code = 502
    detail = "Could not send the WhatsApp message — please try again."


class WhatsAppProvider(ABC):
    @abstractmethod
    async def send(self, to_phone: str | None, message: str) -> None: ...

    # Alias for send() — same thing, named to read clearly next to
    # send_document() below at call sites that send either kind.
    async def send_text(self, to_phone: str | None, message: str) -> None:
        await self.send(to_phone, message)

    @abstractmethod
    async def send_document(self, to_phone: str | None, message: str, document_url: str, filename: str) -> None: ...

    # send/send_document above only work within WhatsApp's 24h customer-
    # initiated window — confirmed via real testing (Meta accepts the
    # request, 200 OK, but never actually delivers it outside that window).
    # This is the one that can cold-message a customer who hasn't messaged
    # first, which is the actual Offers/Credit Reminder use case — but only
    # for a name+language Meta has pre-approved (see message_templates).
    @abstractmethod
    async def send_template(
        self,
        to_phone: str | None,
        template_name: str,
        language_code: str,
        variables: list[str],
        document_url: str | None = None,
        document_filename: str | None = None,
    ) -> None: ...

    # Fetches the template's real approved body text + review status
    # straight from Meta, rather than keeping a second, hand-copied version
    # of the wording in this codebase that could silently drift from
    # whatever is actually live there. Only MetaWhatsAppProvider can do this
    # for real; DevLogWhatsAppProvider returns a clearly-labeled stand-in.
    @abstractmethod
    async def get_template_info(self, template_name: str, language_code: str) -> dict: ...


class DevLogWhatsAppProvider(WhatsAppProvider):
    """No real WhatsApp Business API call is made — the message (and, for a
    document send, the file URL) is logged server-side instead. The safe
    default everywhere (including production until SMS_PROVIDER is
    deliberately switched to "meta") so local dev and testing never hits
    the real API or sends a real message to a real customer.
    """

    async def send(self, to_phone: str | None, message: str) -> None:
        logger.warning("DEV WhatsApp to %s: %s", to_phone or "(no phone on file)", message)

    async def send_document(self, to_phone: str | None, message: str, document_url: str, filename: str) -> None:
        logger.warning(
            "DEV WhatsApp document to %s: %s (file: %s, %s)",
            to_phone or "(no phone on file)",
            message,
            filename,
            document_url,
        )

    async def send_template(
        self,
        to_phone: str | None,
        template_name: str,
        language_code: str,
        variables: list[str],
        document_url: str | None = None,
        document_filename: str | None = None,
    ) -> None:
        logger.warning(
            "DEV WhatsApp template to %s: %s (%s) vars=%s doc=%s",
            to_phone or "(no phone on file)",
            template_name,
            language_code,
            variables,
            document_url,
        )

    async def get_template_info(self, template_name: str, language_code: str) -> dict:
        return {
            "status": "DEV",
            "header_format": None,
            "body_text": f"[DEV MODE — no real Meta template fetched for {template_name} ({language_code})]",
        }


class MetaWhatsAppProvider(WhatsAppProvider):
    """Real WhatsApp send via Meta's Cloud API — POST /{PHONE_NUMBER_ID}/messages,
    Bearer auth, one call per message (text, document, or template).

    Raises WhatsAppSendError (or AppError if unconfigured) rather than ever
    returning a fake success — same contract as Fast2SMSProvider used to
    follow (see git history) and send_email still does. Callers already
    handle this: the Offers dispatch loop (offer_service.py) catches it
    per-recipient and records "failed"; the Credit Reminder endpoint lets it
    propagate as a clean AppError response instead of claiming the reminder
    was sent.

    Document sends use Meta's `document.link` field (a plain HTTPS URL)
    rather than pre-uploading to Meta's own /media endpoint first — verified
    against Meta's current docs: the document object accepts either `id`
    (pre-uploaded media) or `link` (an externally-hosted URL) directly.
    Meta's own docs note `id` performs slightly better, but `link` needs no
    upload step at all, which is what actually keeps this simple — an R2
    presigned URL fed straight to `link` works as-is.
    """

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {settings.meta_whatsapp_access_token}"}

    def _url(self) -> str:
        return f"https://graph.facebook.com/{_META_GRAPH_VERSION}/{settings.meta_whatsapp_phone_number_id}/messages"

    def _check_configured(self) -> None:
        if not settings.meta_whatsapp_access_token or not settings.meta_whatsapp_phone_number_id:
            raise AppError(
                "WhatsApp sending is not configured — set META_WHATSAPP_ACCESS_TOKEN and "
                "META_WHATSAPP_PHONE_NUMBER_ID to send real WhatsApp messages."
            )

    async def _post(self, payload: dict, to_phone: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=_META_TIMEOUT_SECONDS) as client:
                response = await client.post(self._url(), json=payload, headers=self._headers())
        except httpx.TimeoutException as exc:
            logger.error("Meta WhatsApp request to %s timed out (token %s)", to_phone, _mask(settings.meta_whatsapp_access_token))
            raise WhatsAppSendError("WhatsApp provider timed out — please try again.") from exc
        except httpx.HTTPError as exc:
            logger.error("Meta WhatsApp request to %s failed: %s", to_phone, exc)
            raise WhatsAppSendError(f"Could not reach the WhatsApp provider: {exc}") from exc

        try:
            body = response.json()
        except ValueError:
            body = None

        if response.status_code != 200:
            # Meta's error shape: {"error": {"message": ..., "type": ...,
            # "code": ..., "error_subcode": ..., "fbtrace_id": ...}}. Covers
            # every realistic failure explicitly: an expired/invalid token
            # and a bad/unregistered recipient both come back as a 400/401
            # with a message here — never a silent success either way.
            error = (body or {}).get("error") if isinstance(body, dict) else None
            reason = error.get("message") if isinstance(error, dict) else response.text
            code = error.get("code") if isinstance(error, dict) else None
            logger.error(
                "Meta WhatsApp send to %s failed (status %s, code %s, token %s): %s",
                to_phone,
                response.status_code,
                code,
                _mask(settings.meta_whatsapp_access_token),
                reason,
            )
            raise WhatsAppSendError(f"WhatsApp provider rejected the message: {reason}")

        message_id = None
        if isinstance(body, dict):
            messages = body.get("messages") or []
            message_id = messages[0].get("id") if messages else None
        logger.info("Meta WhatsApp send to %s ok — message_id=%s", to_phone, message_id)

    async def send(self, to_phone: str | None, message: str) -> None:
        self._check_configured()
        if not to_phone:
            raise WhatsAppSendError("No phone number on file for this recipient.")
        formatted = _to_e164(to_phone)
        payload = {
            "messaging_product": "whatsapp",
            "to": formatted,
            "type": "text",
            "text": {"body": message},
        }
        await self._post(payload, formatted)

    async def send_document(self, to_phone: str | None, message: str, document_url: str, filename: str) -> None:
        self._check_configured()
        if not to_phone:
            raise WhatsAppSendError("No phone number on file for this recipient.")
        formatted = _to_e164(to_phone)
        payload = {
            "messaging_product": "whatsapp",
            "to": formatted,
            "type": "document",
            "document": {"link": document_url, "filename": filename, "caption": message},
        }
        await self._post(payload, formatted)

    async def send_template(
        self,
        to_phone: str | None,
        template_name: str,
        language_code: str,
        variables: list[str],
        document_url: str | None = None,
        document_filename: str | None = None,
    ) -> None:
        self._check_configured()
        if not to_phone:
            raise WhatsAppSendError("No phone number on file for this recipient.")
        formatted = _to_e164(to_phone)

        components = []
        if document_url:
            # A template whose HEADER component is type=document requires a
            # document parameter on every send using it — there's no way to
            # define one "optional" header on a single template, which is
            # exactly why credit_reminder / credit_reminder_with_bill are
            # two separate templates rather than one with a sometimes-empty
            # header (see CreditCustomerService.send_reminder).
            components.append({
                "type": "header",
                "parameters": [
                    {"type": "document", "document": {"link": document_url, "filename": document_filename or "document.pdf"}}
                ],
            })
        if variables:
            # Positional {{1}}, {{2}}, ... — order here must match the
            # order the template's own body text references them in.
            components.append({"type": "body", "parameters": [{"type": "text", "text": v} for v in variables]})

        payload = {
            "messaging_product": "whatsapp",
            "to": formatted,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
                "components": components,
            },
        }
        await self._post(payload, formatted)

    async def get_template_info(self, template_name: str, language_code: str) -> dict:
        self._check_configured()
        if not settings.meta_whatsapp_business_account_id:
            raise AppError(
                "WhatsApp sending is not configured — set META_WHATSAPP_BUSINESS_ACCOUNT_ID to preview templates."
            )
        url = f"https://graph.facebook.com/{_META_GRAPH_VERSION}/{settings.meta_whatsapp_business_account_id}/message_templates"
        params = {"name": template_name, "fields": "name,language,status,components"}
        try:
            async with httpx.AsyncClient(timeout=_META_TIMEOUT_SECONDS) as client:
                response = await client.get(url, params=params, headers=self._headers())
        except httpx.HTTPError as exc:
            logger.error("Meta template lookup for %s failed: %s", template_name, exc)
            raise WhatsAppSendError(f"Could not reach the WhatsApp provider: {exc}") from exc

        try:
            body = response.json()
        except ValueError:
            body = None

        if response.status_code != 200:
            error = (body or {}).get("error") if isinstance(body, dict) else None
            reason = error.get("message") if isinstance(error, dict) else response.text
            raise WhatsAppSendError(f"WhatsApp provider rejected the template lookup: {reason}")

        candidates = (body or {}).get("data") or []
        match = next((c for c in candidates if c.get("language") == language_code), None)
        if match is None:
            raise AppError(f"Template {template_name!r} ({language_code}) was not found on Meta.")

        components = match.get("components") or []
        body_component = next((c for c in components if c.get("type") == "BODY"), None)
        header_component = next((c for c in components if c.get("type") == "HEADER"), None)
        return {
            "status": match.get("status", "UNKNOWN"),
            "header_format": header_component.get("format") if header_component else None,
            "body_text": body_component.get("text", "") if body_component else "",
        }


def get_whatsapp_provider() -> WhatsAppProvider:
    if settings.sms_provider == "dev":
        return DevLogWhatsAppProvider()
    if settings.sms_provider == "meta":
        return MetaWhatsAppProvider()
    raise NotImplementedError(
        f"No WhatsAppProvider implemented for SMS_PROVIDER={settings.sms_provider!r} yet — "
        "add one to app/core/sms.py."
    )

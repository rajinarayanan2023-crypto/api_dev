import logging
import re
from abc import ABC, abstractmethod

import httpx

from app.core.config import get_settings
from app.core.exceptions import AppError

logger = logging.getLogger("app.sms")
settings = get_settings()

# Fast2SMS's one bulkV2 endpoint serves both routes — "q" (quick, used here:
# works immediately off just an API key, no DLT template needed) and "dlt"
# (the production route, needs an approved template/message id + sender id).
# Both are simple POSTs to the same URL with a different `route` value —
# switching later is a config/payload change here, not a new endpoint.
_FAST2SMS_URL = "https://www.fast2sms.com/dev/bulkV2"
_FAST2SMS_TIMEOUT_SECONDS = 8.0  # fail fast rather than hang a login request


def _mask(key: str) -> str:
    """Never put a real API key in a log line — first/last 3 chars only."""
    if len(key) <= 6:
        return "***"
    return f"{key[:3]}...{key[-3:]}"


def _digits_only(phone: str) -> str:
    """Fast2SMS wants a bare 10-digit Indian mobile number — no +91/leading
    0/spaces/dashes. Every phone number in this app is already stored that
    way, but this strips anything else defensively rather than trusting it.
    """
    digits = re.sub(r"\D", "", phone or "")
    return digits[-10:] if len(digits) >= 10 else digits


class SmsSendError(AppError):
    status_code = 502
    detail = "Could not send the SMS — please try again."


class SmsProvider(ABC):
    @abstractmethod
    async def send(self, to_phone: str | None, message: str) -> None: ...


class DevLogSmsProvider(SmsProvider):
    """No real SMS is sent — the message (OTP code included) is logged
    server-side instead. The safe default everywhere (including production
    until SMS_PROVIDER is deliberately switched to "fast2sms") so local dev
    and testing never hits the real API or incurs real SMS cost.
    """

    async def send(self, to_phone: str | None, message: str) -> None:
        logger.warning("DEV SMS to %s: %s", to_phone or "(no phone on file)", message)


class Fast2SMSProvider(SmsProvider):
    """Real SMS via Fast2SMS's quick-send route ("q") — works immediately
    off just an API key, no DLT template registration needed. Once a
    DLT-approved template is available, switch to it by changing `_route()`
    /`_payload()` below to route="dlt" (+ FAST2SMS_SENDER_ID, + a template id
    in place of the free-text message) — the send() signature and every
    caller (OTP login, Offers SMS) stay exactly the same.

    Raises SmsSendError (or AppError if unconfigured) rather than ever
    returning a fake success — same contract as DevLogSmsProvider silently
    succeeding, and the same "never swallow a real failure" rule email.py's
    send_email follows. Callers already handle this: the Offers dispatch
    loop (offer_service.py) catches it per-recipient and records "failed";
    the OTP login route (auth_controller.py) catches it and reports a clean
    error instead of claiming the code was sent.
    """

    def _payload(self, phone: str, message: str) -> dict:
        # route="q": Fast2SMS's quick/transactional route. A DLT template id
        # would replace `message` here and add `sender_id` once approved —
        # everything else (auth, numbers, error handling) is unchanged.
        return {
            "route": "q",
            "message": message,
            "language": "english",
            "flash": 0,
            "numbers": _digits_only(phone),
        }

    async def send(self, to_phone: str | None, message: str) -> None:
        if not settings.fast2sms_api_key:
            raise AppError("SMS sending is not configured — set FAST2SMS_API_KEY to send real SMS.")
        if not to_phone:
            raise SmsSendError("No phone number on file for this recipient.")

        numbers = _digits_only(to_phone)
        if len(numbers) != 10:
            raise SmsSendError(f"'{to_phone}' is not a valid 10-digit mobile number.")

        headers = {"authorization": settings.fast2sms_api_key}
        payload = self._payload(numbers, message)

        try:
            async with httpx.AsyncClient(timeout=_FAST2SMS_TIMEOUT_SECONDS) as client:
                response = await client.post(_FAST2SMS_URL, data=payload, headers=headers)
        except httpx.TimeoutException as exc:
            logger.error("Fast2SMS request to %s timed out (key %s)", numbers, _mask(settings.fast2sms_api_key))
            raise SmsSendError("SMS provider timed out — please try again.") from exc
        except httpx.HTTPError as exc:
            logger.error("Fast2SMS request to %s failed: %s", numbers, exc)
            raise SmsSendError(f"Could not reach the SMS provider: {exc}") from exc

        # Fast2SMS returns HTTP 200 for most logical failures too (bad key,
        # bad number, low balance, ...) — the real signal is the `return`
        # field in the JSON body, not the status code. Still guard the
        # status code separately since an auth failure at the HTTP layer
        # (e.g. a malformed key) isn't guaranteed to come back as JSON.
        try:
            body = response.json()
        except ValueError:
            body = None

        ok = isinstance(body, dict) and body.get("return") is True
        if response.status_code != 200 or not ok:
            reason = (body or {}).get("message") if isinstance(body, dict) else response.text
            logger.error(
                "Fast2SMS send to %s failed (status %s, key %s): %s",
                numbers,
                response.status_code,
                _mask(settings.fast2sms_api_key),
                reason,
            )
            raise SmsSendError(f"SMS provider rejected the message: {reason}")

        logger.info("Fast2SMS send to %s ok — request_id=%s", numbers, body.get("request_id"))


def get_sms_provider() -> SmsProvider:
    if settings.sms_provider == "dev":
        return DevLogSmsProvider()
    if settings.sms_provider == "fast2sms":
        return Fast2SMSProvider()
    raise NotImplementedError(
        f"No SmsProvider implemented for SMS_PROVIDER={settings.sms_provider!r} yet — "
        "add one to app/core/sms.py."
    )


class WhatsAppProvider(ABC):
    @abstractmethod
    async def send(self, to_phone: str | None, message: str) -> None: ...


class DevLogWhatsAppProvider(WhatsAppProvider):
    """Same stand-in as DevLogSmsProvider above — no WhatsApp Business API
    account exists yet, so this just logs. Offer sends used to open a wa.me
    deep link client-side instead of a real send; that only works for one
    recipient at a time, which doesn't fit a bulk send with per-recipient
    tracking, so it's replaced by this (also-not-real-yet) server-side path.
    """

    async def send(self, to_phone: str | None, message: str) -> None:
        logger.warning("DEV WhatsApp to %s: %s", to_phone or "(no phone on file)", message)


def get_whatsapp_provider() -> WhatsAppProvider:
    if settings.sms_provider == "dev":
        return DevLogWhatsAppProvider()
    raise NotImplementedError(
        f"No WhatsAppProvider implemented for SMS_PROVIDER={settings.sms_provider!r} yet — "
        "add one to app/core/sms.py."
    )

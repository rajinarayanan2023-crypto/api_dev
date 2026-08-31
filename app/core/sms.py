import logging
from abc import ABC, abstractmethod

from app.core.config import get_settings

logger = logging.getLogger("app.sms")
settings = get_settings()


class SmsProvider(ABC):
    @abstractmethod
    async def send(self, to_phone: str | None, message: str) -> None: ...


class DevLogSmsProvider(SmsProvider):
    """No real SMS is sent — the message (OTP code included) is logged
    server-side instead. This is the only provider implemented today, since
    no SMS account/credentials exist yet; swap in a real one (Twilio, MSG91,
    ...) by adding a class here that calls its API, and returning it from
    get_sms_provider() below once real credentials are in .env.
    """

    async def send(self, to_phone: str | None, message: str) -> None:
        logger.warning("DEV SMS to %s: %s", to_phone or "(no phone on file)", message)


def get_sms_provider() -> SmsProvider:
    if settings.sms_provider == "dev":
        return DevLogSmsProvider()
    raise NotImplementedError(
        f"No SmsProvider implemented for SMS_PROVIDER={settings.sms_provider!r} yet — "
        "add one to app/core/sms.py."
    )

"""In-memory login-OTP store. Never persisted to Postgres — a code only
needs to survive a few minutes, and losing it on process restart is fine
(the user just signs in again).
"""
import secrets
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings

settings = get_settings()

OTP_EXPIRE_MINUTES = 1.5
OTP_MAX_ATTEMPTS = 3


# Human-readable phrasing of OTP_EXPIRE_MINUTES for the SMS text itself (see
# auth_controller.login) — kept next to the constant so the two can never
# drift out of sync the way a separately hand-typed "5 minutes" string did.
def otp_expiry_phrase() -> str:
    total_seconds = round(OTP_EXPIRE_MINUTES * 60)
    minutes, seconds = divmod(total_seconds, 60)
    parts = []
    if minutes:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if seconds:
        parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
    return " ".join(parts) or "0 seconds"

otp_store: dict[str, dict] = {}  # user_id -> {otp, expires_at, attempts}


def generate_otp(user_id: str) -> str:
    otp = "".join(secrets.choice("0123456789") for _ in range(settings.otp_length))
    otp_store[user_id] = {
        "otp": otp,
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRE_MINUTES),
        "attempts": 0,
    }
    return otp


def verify_otp(user_id: str, otp: str) -> tuple[bool, str]:
    entry = otp_store.get(user_id)
    if entry is None:
        return False, "No pending OTP for this user. Please sign in again."

    if datetime.now(timezone.utc) > entry["expires_at"]:
        del otp_store[user_id]
        return False, "OTP expired. Please sign in again."

    if entry["attempts"] >= OTP_MAX_ATTEMPTS:
        del otp_store[user_id]
        return False, "Too many incorrect attempts. Please sign in again."

    if otp != entry["otp"]:
        entry["attempts"] += 1
        return False, "Incorrect OTP. Please try again."

    del otp_store[user_id]
    return True, "OK"

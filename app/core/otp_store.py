"""In-memory login-OTP store. Never persisted to Postgres — a code only
needs to survive a few minutes, and losing it on process restart is fine
(the user just signs in again).
"""
import secrets
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings

settings = get_settings()

OTP_EXPIRE_MINUTES = 5
OTP_MAX_ATTEMPTS = 3

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

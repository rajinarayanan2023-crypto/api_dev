import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum

import jwt
from passlib.context import CryptContext

from app.core.config import get_settings

settings = get_settings()

# Argon2 has no input-length caveats (unlike bcrypt's 72-byte cap) and is the
# current OWASP-recommended default for new applications.
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

# A valid hash with no matching real password, used to run a verify() against
# a fixed cost when a lookup finds no user — keeps login response timing from
# revealing whether an email is registered.
DUMMY_PASSWORD_HASH = pwd_context.hash(secrets.token_urlsafe(32))


class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def _create_token(subject: str, token_type: TokenType, expires_delta: timedelta, extra_claims: dict | None = None) -> tuple[str, str]:
    """Returns (encoded_jwt, jti). jti lets refresh tokens be revoked individually."""
    now = datetime.now(timezone.utc)
    jti = str(uuid.uuid4())
    payload = {
        "sub": subject,
        "type": token_type.value,
        "iat": now,
        "exp": now + expires_delta,
        "jti": jti,
    }
    if extra_claims:
        payload.update(extra_claims)
    encoded = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    return encoded, jti


def create_access_token(subject: str, role: str) -> str:
    token, _ = _create_token(
        subject=subject,
        token_type=TokenType.ACCESS,
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
        extra_claims={"role": role},
    )
    return token


def create_refresh_token(subject: str) -> tuple[str, str, datetime]:
    """Returns (token, jti, expires_at) so the caller can persist a hash of it."""
    expires_delta = timedelta(days=settings.refresh_token_expire_days)
    token, jti = _create_token(subject=subject, token_type=TokenType.REFRESH, expires_delta=expires_delta)
    expires_at = datetime.now(timezone.utc) + expires_delta
    return token, jti, expires_at


def decode_token(token: str) -> dict:
    """Raises jwt.PyJWTError (or a subclass) on any invalid/expired/tampered token."""
    return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])


def hash_token(token: str) -> str:
    """One-way hash used to store refresh tokens at rest — never store raw tokens in the DB."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_temp_password(length: int = 16) -> str:
    """For admin-provisioned accounts that must reset their password on first login."""
    return secrets.token_urlsafe(length)

from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_name: str = "Petrol Bunk Manager API"
    environment: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # --- Security ---
    secret_key: str = Field(..., min_length=32)
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    # A session is force-expired after this long with no successful refresh,
    # regardless of refresh_token_expire_days — enforced in AuthService.refresh().
    idle_timeout_minutes: int = 240

    # --- Database ---
    postgres_user: str
    postgres_password: str
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str
    # Neon (and most managed Postgres) requires TLS. asyncpg and psycopg2
    # take this differently — asyncpg wants a bare "ssl" connect arg
    # (see database.py), psycopg2 accepts "sslmode" directly in the DSN.
    postgres_sslmode: str = "disable"

    # --- CORS / hosts ---
    cors_origins: str = ""
    allowed_hosts: str = "localhost,127.0.0.1"

    # --- Rate limiting ---
    rate_limit_login: str = "5/minute"
    rate_limit_default: str = "100/minute"

    # --- Login OTP ---
    # Expiry/max-attempts live in app/core/otp_store.py (in-memory, not DB
    # config) since they're not meant to be tuned per-deployment.
    otp_length: int = 6
    # "dev" logs the OTP (and any Offers SMS) server-side instead of sending
    # anything real — the safe default everywhere, including production
    # until this is deliberately switched. "fast2sms" sends for real via
    # Fast2SMSProvider (app/core/sms.py). Same switch covers both the OTP
    # login flow and the Offers module's SMS channel — one flag, one
    # provider class, no separate implementations.
    sms_provider: str = "dev"

    # --- SMS (Fast2SMS) ---
    # Fast2SMS's quick-send route ("q") works immediately with just an API
    # key — no DLT template registration needed — which is why it's used for
    # now. Lazy-validated like R2/SMTP above: only required once a send is
    # actually attempted (see Fast2SMSProvider.send), so the app still boots
    # fine with SMS_PROVIDER=dev and this unset.
    fast2sms_api_key: str = ""
    # Unused by the quick-send route today. Once a DLT-approved template is
    # approved, the production route needs this (plus a template/message id)
    # — kept here now so switching later is a config change, not a rewrite.
    fast2sms_sender_id: str = ""

    # --- File uploads ---
    # Local-disk storage (see app/main.py's StaticFiles mount) is now only a
    # fallback for bills uploaded before the R2 move — every new upload goes
    # straight to Cloudflare R2 via a presigned URL (see app/core/s3.py,
    # upload_controller.py).
    upload_dir: str = "uploads"
    upload_max_size_mb: int = 10

    # --- File uploads (Cloudflare R2) ---
    # R2 is S3-API-compatible (see app/core/s3.py, which talks to it via
    # boto3's S3 client pointed at R2's endpoint) — these are R2's own
    # credentials from the Cloudflare dashboard, NOT AWS IAM credentials.
    # Deliberately no defaults for the credential/bucket fields — left unset
    # until a real bucket exists rather than silently pointing at nothing.
    # Only validated (in app/core/s3.py) at the point an upload endpoint is
    # actually called, so a deployment that doesn't use uploads yet can still
    # start up without them.
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = ""

    # --- Email (SMTP) ---
    # Same lazy pattern as R2 above: no default for the credential fields,
    # left unset until real ones exist — only validated (in app/core/email.py)
    # at the point the send-audit-email endpoint is actually called, so a
    # deployment that doesn't use email yet can still start up without them.
    # SMTP_APP_PASSWORD is a Gmail App Password (myaccount.google.com/apppasswords),
    # NOT the account's real login password — Gmail rejects SMTP auth with the
    # real password once 2FA is on, which it must be to issue an App Password.
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_app_password: str = ""
    smtp_from_name: str = "GM Fuel Station Audit"

    @field_validator("secret_key")
    @classmethod
    def secret_key_must_not_be_placeholder(cls, v: str) -> str:
        if v.startswith("replace-with") or v.startswith("change-this"):
            raise ValueError("SECRET_KEY must be set to a real secret, not the placeholder value")
        return v

    @property
    def _credentials(self) -> str:
        # A raw password can contain characters (@, :, /, ?, #, ...) that are
        # URL delimiters — quote_plus escapes them so the DSN parses correctly
        # regardless of what's in postgres_password.
        return f"{quote_plus(self.postgres_user)}:{quote_plus(self.postgres_password)}"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self._credentials}"
            f"@{self.postgres_host}:{self.postgres_port}/{quote_plus(self.postgres_db)}"
        )

    @property
    def sync_database_url(self) -> str:
        """Used by Alembic, which runs migrations over a sync driver."""
        return (
            f"postgresql+psycopg2://{self._credentials}"
            f"@{self.postgres_host}:{self.postgres_port}/{quote_plus(self.postgres_db)}"
            f"?sslmode={self.postgres_sslmode}"
        )

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def allowed_hosts_list(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

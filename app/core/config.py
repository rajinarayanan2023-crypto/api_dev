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
    otp_length: int = 6
    otp_expire_minutes: int = 5
    otp_max_attempts: int = 5
    # "dev" logs the OTP server-side instead of sending a real SMS — no
    # provider account exists yet. See app/core/sms.py.
    sms_provider: str = "dev"
    # Temporary bypass switch: set to false to skip the OTP step entirely
    # (see AuthService.login_without_otp) while it's not fully wired to a
    # real SMS provider yet. Flip back to true to restore the OTP flow with
    # no code changes.
    otp_enabled: bool = True

    # --- File uploads ---
    # Local-disk storage for bill photos/documents (see UploadController) —
    # a stopgap until this moves to real object storage (S3/R2/etc.) if the
    # app ever runs on more than one server. Files land here and are served
    # back out at /uploads/<filename> (see app/main.py's StaticFiles mount).
    upload_dir: str = "uploads"
    upload_max_size_mb: int = 10


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

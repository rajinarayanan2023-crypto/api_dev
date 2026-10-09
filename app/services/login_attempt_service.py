from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import TooManyAttemptsError
from app.models.login_attempt import LoginAttempt
from app.repositories.login_attempt_repository import LoginAttemptRepository

settings = get_settings()


class LoginAttemptService:
    """Two real gaps this closes together: there was no durable record of
    failed logins at all (console logs only, if that), and slowapi's
    per-IP rate limiting (core/rate_limit.py) structurally can't catch many
    different IPs each trying a few passwords against the SAME account —
    check_lockout below is keyed by identifier, read straight off this
    table, not by IP.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.attempts = LoginAttemptRepository(session)

    async def record(
        self,
        *,
        identifier: str,
        action: str,
        success: bool,
        reason: str | None = None,
        user_id=None,
        ip_address: str | None = None,
    ) -> None:
        # Explicit commit — not just flush — is deliberate and required here.
        # This almost always runs right before the endpoint raises an auth
        # error (wrong password, locked out, ...); app/core/database.py's
        # get_db() rolls back the WHOLE session when a request ends in an
        # exception, which would silently erase an uncommitted attempt row
        # along with it (confirmed via a real end-to-end test: 6 real failed
        # /auth/login calls produced zero rows in Login_Attempts until this
        # commit was added). An audit record of a failed attempt has to
        # survive precisely the failure it's recording.
        await self.attempts.create(
            LoginAttempt(
                identifier=identifier,
                action=action,
                success=success,
                reason=reason,
                user_id=user_id,
                ip_address=ip_address,
            )
        )
        await self.session.commit()

    async def check_lockout(
        self, identifier: str, action: str, *, ip_address: str | None = None, user_id=None
    ) -> None:
        """Raises TooManyAttemptsError (and records the block itself, so a
        locked-out attempt shows up on the Login Attempts screen same as any
        other failure) if `identifier` has racked up
        settings.login_lockout_max_failures failed `action` attempts within
        the last settings.login_lockout_window_minutes — regardless of
        which IP they came from. Call this BEFORE checking a password, so a
        locked-out attempt never even reaches the real credential check.
        """
        since = datetime.now(timezone.utc) - timedelta(minutes=settings.login_lockout_window_minutes)
        failures = await self.attempts.count_recent_failures(identifier, action, since)
        if failures >= settings.login_lockout_max_failures:
            await self.record(
                identifier=identifier,
                action=action,
                success=False,
                reason="locked_out",
                user_id=user_id,
                ip_address=ip_address,
            )
            raise TooManyAttemptsError(
                f"Too many failed attempts. Please try again in {settings.login_lockout_window_minutes} minutes."
            )

    async def list_attempts(
        self,
        offset: int = 0,
        limit: int = 500,
        *,
        identifier: str | None = None,
        success: bool | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[LoginAttempt]:
        return await self.attempts.list_recent(
            offset=offset, limit=limit, identifier=identifier, success=success, date_from=date_from, date_to=date_to
        )

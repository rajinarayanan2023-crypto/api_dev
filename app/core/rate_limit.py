from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings

settings = get_settings()

# Keyed by client IP. Behind a reverse proxy, make sure it forwards
# X-Forwarded-For and that the proxy itself is trusted, or this can be spoofed.
#
# default_limits applies RATE_LIMIT_DEFAULT to every route automatically
# (via SlowAPIMiddleware, see app/main.py) — this was previously defined in
# config but never actually passed to the Limiter, so nothing except the
# handful of routes explicitly decorated with @limiter.limit(...) below had
# any rate limiting at all. A route's own @limiter.limit(...) still
# overrides this default for that route (e.g. /auth/login's much stricter
# RATE_LIMIT_LOGIN).
limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit_default])
